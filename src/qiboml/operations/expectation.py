"""Compute expectation values of target observables with the freedom of setting any qibo's backend."""

from typing import List, Optional, Union

import qibo
import qibo.backends
from qibo.backends import construct_backend
from qibo.config import raise_error
from qibojit.backends import NumbaBackend

from qiboml.backends import JaxBackend, TensorflowBackend


def expectation(
    observable: qibo.hamiltonians.Hamiltonian,
    circuit: qibo.Circuit,
    initial_state: Optional[Union[List, qibo.Circuit]] = None,
    nshots: int = None,
    exec_backend: qibo.backends.Backend = NumbaBackend,
    differentiation_rule: Optional[callable] = None,
):
    """
    Compute the expectation value of ``observable`` over the state obtained by
    executing ``circuit`` starting from ``initial_state``. The final state is
    reconstructed from ``nshots`` execution of ``circuit`` on the selected ``backend``.
    In addition, a differentiation rule can be set, which is going to be integrated
    within the used high-level framework. For example, if TensorFlow is used
    in the user code and one parameter shift rule is selected as differentiation
    rule, the expectation value is computed informing the TensorFlow graph to
    use as gradient the output of the parameter shift rule executed on the selected
    backend.

    Args:
        observable (qibo.Hamiltonian): the observable whose expectation value has
            to be computed.
        circuit (qibo.Circuit): quantum circuit returning the final state over which
            the expectation value of ``observable`` is computed.
        initial_state (Optional[Union[List, qibo.Circuit]]): initial state on which
            the quantum circuit is applied.
        nshots (int): number of times the quantum circuit is executed. Increasing
            the number of shots will reduce the variance of the estimated expectation
            value while increasing the computational cost of the operation.
        exec_backend (qibo.backend.Backend): backend on which the circuit
            is executed. This same backend is used if the chosen differentiation
            rule makes use of expectation values.
        differentiation_rule (Optional[callable]): the chosen differentiation
            rule. It can be selected among the methods implemented in
            ``qiboml.differentiation``.
    """

    # read the frontend user choice
    frontend = observable.backend

    kwargs = dict(
        observable=observable,
        circuit=circuit,
        initial_state=initial_state,
        nshots=nshots,
        exec_backend=exec_backend,
        differentiation_rule=differentiation_rule,
    )

    if differentiation_rule is not None:
        if isinstance(frontend, TensorflowBackend):
            return _with_tf(**kwargs)

        if isinstance(frontend, JaxBackend):
            return _with_jax(**kwargs)

    elif nshots is None:
        return _exact(observable, circuit, initial_state, exec_backend)
    else:
        return _with_shots(observable, circuit, initial_state, nshots, exec_backend)


def _exact(observable, circuit, initial_state, exec_backend):
    """Helper function to compute exact expectation values."""
    return observable.expectation(
        exec_backend.execute_circuit(
            circuit=circuit, initial_state=initial_state
        ).state()
    )


def _with_shots(observable, circuit, initial_state, nshots, exec_backend):
    """Helper function to compute expectation values from samples."""
    return exec_backend.execute_circuit(
        circuit=circuit, initial_state=initial_state, nshots=nshots
    ).expectation_from_samples(observable)


def _with_tf(
    observable,
    circuit,
    initial_state,
    nshots,
    exec_backend,
    differentiation_rule,
):
    """
    Compute expectation sample integrating the custom differentiation rule with
    TensorFlow's automatic differentiation.
    """
    import tensorflow as tf  # pylint: disable=import-error

    params = circuit.get_parameters()
    nparams = len(params)

    @tf.custom_gradient
    def _expectation(params):
        params = tf.Variable(params)

        def grad(upstream):
            gradients = []
            for p in range(nparams):
                gradients.append(
                    upstream
                    * differentiation_rule(
                        circuit=circuit,
                        hamiltonian=observable,
                        parameter_index=p,
                        initial_state=initial_state,
                        nshots=nshots,
                        exec_backend=exec_backend,
                    )
                )
            return gradients

        if nshots is None:
            expval = _exact(observable, circuit, initial_state, exec_backend)
        else:
            expval = _with_shots(
                observable, circuit, initial_state, nshots, exec_backend
            )

        return expval, grad

    return _expectation(params)


def _with_jax(
    observable,
    circuit,
    initial_state,
    nshots,
    exec_backend,
    differentiation_rule,
):
    """
    Compute expectation sample integrating the custom differentiation rule with
    TensorFlow's automatic differentiation.
    """
    import jax  # pylint: disable=import-error

    params = circuit.get_parameters()

    @jax.custom_gradient
    def _expectation(params):
        params = jax.numpy.array(params)

        def grad(params):
            gradients = []
            for p in range(len(params)):
                gradients.append(
                    differentiation_rule(
                        circuit=circuit,
                        hamiltonian=observable,
                        parameter_index=p,
                        initial_state=initial_state,
                        nshots=nshots,
                        exec_backend=exec_backend,
                    )
                )
                print("ciao")
            return jax.numpy.array(gradients)

        if nshots is None:
            expval = jax.jit(_exact(observable, circuit, initial_state, exec_backend))
        else:
            expval = jax.jit(
                _with_shots(observable, circuit, initial_state, nshots, exec_backend)
            )

        return expval, lambda g: g * jax.jit(grad(params))

    return jax.jit(_expectation(params))

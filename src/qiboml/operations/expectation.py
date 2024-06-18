"""Compute expectation values of target observables with the freedom of setting any qibo's backend."""

from typing import List, Optional, Union

import qibo
import torch
from qibo.backends import Backend, NumpyBackend
from qibo.config import raise_error

from qiboml.backends import PyTorchBackend, TensorflowBackend


def expectation(
    observable: qibo.hamiltonians.Hamiltonian,
    circuit: qibo.Circuit,
    initial_state: Optional[Union[List, qibo.Circuit]] = None,
    nshots: int = None,
    exec_backend: Backend = NumpyBackend(),
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
        elif isinstance(frontend, PyTorchBackend):
            return _with_torch(**kwargs)
        else:
            raise_error(ValueError, f" Interface for {frontend} is not supported.")

    elif nshots is None:
        return _exact(observable, circuit, initial_state, exec_backend)
    else:
        return _with_shots(observable, circuit, initial_state, nshots, exec_backend)


def _exact(observable, circuit, initial_state, exec_backend):
    """Helper function to compute exact expectation values."""
    return exec_backend.calculate_expectation_state(
        hamiltonian=exec_backend.cast(observable.matrix),
        state=exec_backend.execute_circuit(
            circuit=circuit, initial_state=initial_state
        ).state(),
        normalize=False,
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

    kwargs = dict(
        hamiltonian=observable,
        circuit=circuit,
        initial_state=initial_state,
        exec_backend=exec_backend,
        nshots=nshots if nshots is not None else None,
    )

    if nshots is not None:
        kwargs.update({"nshots": nshots})

    @tf.custom_gradient
    def _expectation(params):

        def grad(upstream):
            gradients = upstream * tf.stack(differentiation_rule(**kwargs))
            return tf.unstack(gradients)

        if nshots is None:
            expval = _exact(observable, circuit, initial_state, exec_backend)
        else:
            expval = _with_shots(
                observable, circuit, initial_state, nshots, exec_backend
            )

        return expval, grad

    return _expectation(params)


def _with_torch(
    observable,
    circuit,
    initial_state,
    nshots,
    exec_backend,
    differentiation_rule,
):
    """
    Compute expectation sample integrating the custom differentiation rule with
    Torch's automatic differentiation.
    """

    kwargs = dict(
        hamiltonian=observable,
        circuit=circuit,
        initial_state=initial_state,
        exec_backend=exec_backend,
        nshots=nshots if nshots is not None else None,
    )

    if nshots is not None:
        kwargs.update({"nshots": nshots})

    params = torch.tensor(
        circuit.get_parameters(), dtype=torch.float64, requires_grad=True
    )

    return _TorchDifferentiableExpectation.apply(
        params,
        observable,
        circuit,
        initial_state,
        nshots,
        exec_backend,
        differentiation_rule,
    )


class _TorchDifferentiableExpectation(torch.autograd.Function):
    @staticmethod
    def forward(
        ctx,
        params,
        observable,
        circuit,
        initial_state,
        nshots,
        exec_backend,
        differentiation_rule,
    ):
        # Save everything needed for the backward pass in ctx
        ctx.save_for_backward(params)
        ctx.observable = observable
        ctx.circuit = circuit
        ctx.initial_state = initial_state
        ctx.nshots = nshots
        ctx.exec_backend = exec_backend
        ctx.differentiation_rule = differentiation_rule

        # Calculate expectation value using exec_backend
        if nshots is None:
            expval = exec_backend.calculate_expectation_state(
                hamiltonian=exec_backend.cast(observable.matrix),
                state=exec_backend.execute_circuit(
                    circuit=circuit, initial_state=initial_state
                ).state(),
                normalize=False,
            )
        else:
            expval = exec_backend.execute_circuit(
                circuit=circuit, initial_state=initial_state, nshots=nshots
            ).expectation_from_samples(observable)

        return expval.clone().detach().to(dtype=torch.float64)

    @staticmethod
    def backward(ctx, grad_output):
        (params,) = ctx.saved_tensors
        observable = ctx.observable
        circuit = ctx.circuit
        initial_state = ctx.initial_state
        nshots = ctx.nshots
        exec_backend = ctx.exec_backend
        differentiation_rule = ctx.differentiation_rule

        kwargs = dict(
            hamiltonian=observable,
            circuit=circuit,
            initial_state=initial_state,
            exec_backend=exec_backend,
            nshots=nshots,
        )

        gradients = (grad_output * torch.tensor(differentiation_rule(**kwargs)))[
            :, None
        ]
        return gradients, None, None, None, None, None, None

from abc import ABC, abstractmethod
from typing import Tuple

from qibo import Circuit, gates
from qibo.config import raise_error


class ReuploadingCircuit(ABC):
    def __init__(self, nqubits: int, nlayers: int, data_dimensionality: Tuple):
        """
        Abstract Data Reuploading Circuit.

        Args:
            nqubits (int): number of qubits;
            nlayers (int): number of layers;
            data_dimensionality (Tuple): data dimensionality.
        """
        self.nqubits = nqubits
        self.nlayers = nlayers
        self.datadim = data_dimensionality
        self.circuit = Circuit(nqubits)

    @abstractmethod
    def _init_parameters(self):
        """
        Initialize the trainable parameters, which don't correspond in general
        to the circuit's parameters.
        """
        raise_error(NotImplementedError)

    @property
    def nparams(self):
        """Number of trainable parameters."""
        return len(self.parameters)

    def set_parameters(self, parameters):
        """Set trainable parameters into the circuit."""
        self.parameters = parameters

    @abstractmethod
    def build_circuit(self):
        """Build the Parametric Circuit according to the chosen strategy."""
        raise_error(NotImplementedError)

    def build_entangling_layer(self):
        """Build circuit's entangling layer structure."""
        c = Circuit(self.nqubits)
        for q in range(0, self.nqubits - 1, 1):
            c.add(gates.CNOT(q0=q, q1=q + 1))
        c.add(gates.CNOT(q0=self.nqubits - 1, q1=0))
        return c

    @abstractmethod
    def inject_data(self, x):
        """Inject data ``x`` into the circuit according to the chosen strategy."""
        raise_error(NotImplementedError)

from abc import ABC, abstractmethod


class Instrument(ABC):
    def __init__(self, model, name):
        self.model = model
        self.name = name

    @abstractmethod
    def parse_data(self, dict_path_to_files):
        pass


from abc import ABC, abstractmethod


class Instrument(ABC):
    def __init__(self, type_, name, model):
        self.type_ = type_
        self.name = name
        self.model = model

    @abstractmethod
    def parse_data(self, dict_path_to_files):
        pass


from abc import ABC, abstractmethod


class Instrument(ABC):
    def __init__(self, type_, name, model, data_root_path):
        self.type_ = type_
        self.name = name
        self.model = model
        self.data_root_path = data_root_path

    @abstractmethod
    def parse_data(self, dict_data_paths):
        pass


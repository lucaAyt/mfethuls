from abc import ABC, abstractmethod
import pandas as pd


class InstrumentParser(ABC):

    def __init__(self):
        self.df = pd.DataFrame()

    @abstractmethod
    def parse(self, df: pd.DataFrame):
        pass

    @staticmethod
    @abstractmethod
    def get_data_df(self):
        pass

    @ abstractmethod
    def clear(self):
        pass


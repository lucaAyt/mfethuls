"""An instrument as ingest uses it: its name, type, model, data folder, parser and characterizer."""


class GenericInstrument:
    def __init__(self, type_, name, model, parser, characterizer=None, data_root_path=None):
        self.type_ = type_
        self.name = name
        self.model = model
        self.data_root_path = data_root_path
        self.parser = parser
        self.characterizer = characterizer

    def __str__(self):
        return f"<Instrument: {self.name} ({self.type_}, {self.model}, {self.data_root_path})>"

    def __repr__(self):
        char = f", characterizer={self.characterizer.__class__.__name__}" if self.characterizer else ""
        return (f"GenericInstrument(name='{self.name}', type='{self.type_}', model='{self.model}', "
                f"parser={self.parser.__class__.__name__}{char}, data_root_path='{self.data_root_path}')")

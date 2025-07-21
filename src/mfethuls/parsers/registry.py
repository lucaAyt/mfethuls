_PARSER_REGISTRY = {}


def register_parser(type_, model):
    def decorator(cls):
        _PARSER_REGISTRY[(type_, model)] = cls()
        return cls

    return decorator


def get_parser(type_, model):
    key = (type_, model)
    if key not in _PARSER_REGISTRY:
        raise ValueError(f"No parser for {type_} {model}")
    return _PARSER_REGISTRY[key]
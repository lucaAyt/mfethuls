_MODEL_REGISTRY = {}


def register_parser(type_, name):
    def decorator(cls):
        _MODEL_REGISTRY[(type_, name)] = cls()
        return cls

    return decorator


def get_model(type_, name):
    key = (type_, name)
    if key not in _MODEL_REGISTRY:
        raise ValueError(f"No model for {type_} {name}")
    return _MODEL_REGISTRY[key]

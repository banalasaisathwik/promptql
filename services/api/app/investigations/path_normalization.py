def normalized_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")

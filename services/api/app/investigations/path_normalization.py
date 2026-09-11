def normalized_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def paths_match(path_a: str, path_b: str) -> bool:
    normalized_a = normalized_path(path_a)
    normalized_b = normalized_path(path_b)
    if normalized_a == normalized_b:
        return True
    segments_a = normalized_a.split("/")
    segments_b = normalized_b.split("/")
    shorter, longer = (
        (segments_a, segments_b)
        if len(segments_a) <= len(segments_b)
        else (segments_b, segments_a)
    )
    if len(shorter) < 2:
        return False
    return longer[len(longer) - len(shorter) :] == shorter

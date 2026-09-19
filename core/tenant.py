LEGACY_PROFILE_ID = 1


def normalize_profile_id(profile_id):
    if profile_id is None:
        return LEGACY_PROFILE_ID
    value = int(profile_id)
    if value < 1:
        raise ValueError("perfil_id inválido")
    return value

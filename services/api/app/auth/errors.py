class UserAlreadyExistsError(RuntimeError):
    pass


class AuthPersistenceError(RuntimeError):
    pass


class CredentialConfigurationError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass

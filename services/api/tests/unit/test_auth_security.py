import unittest

from app.auth.security import hash_password, verify_password


class PasswordHashingTests(unittest.TestCase):
    def test_correct_password_is_accepted(self) -> None:
        password_hash = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", password_hash))

    def test_incorrect_password_is_rejected(self) -> None:
        password_hash = hash_password("correct horse battery staple")

        self.assertFalse(verify_password("wrong password", password_hash))

    def test_hash_output_is_not_the_input_password(self) -> None:
        password_hash = hash_password("correct horse battery staple")

        self.assertNotEqual(password_hash, "correct horse battery staple")

    def test_hashing_the_same_password_twice_produces_different_hashes(self) -> None:
        first_hash = hash_password("correct horse battery staple")
        second_hash = hash_password("correct horse battery staple")

        self.assertNotEqual(first_hash, second_hash)

    def test_malformed_hash_is_rejected_without_raising(self) -> None:
        self.assertFalse(verify_password("anything", "not-a-real-argon2-hash"))


if __name__ == "__main__":
    unittest.main()

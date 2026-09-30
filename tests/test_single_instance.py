import unittest
from voiceflow_core.single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_single_instance_acquisition_and_release(self):
        first = SingleInstance("VoiceFlow_Test_Instance_1")
        self.assertFalse(first.is_running)

        # Second instance with same mutex should detect it is already running
        second = SingleInstance("VoiceFlow_Test_Instance_1")
        self.assertTrue(second.is_running)

        second.release()
        first.release()


if __name__ == "__main__":
    unittest.main()

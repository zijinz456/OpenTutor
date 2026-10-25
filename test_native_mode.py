import unittest
from unittest.mock import patch

from config import settings
from services.agent.code_execution import CodeExecutionAgent, sandbox_runtime_available, get_effective_sandbox_backend


class NativeModeTests(unittest.TestCase):
    def test_disabled_execution_never_probes_a_container(self):
        with patch.object(settings,'code_sandbox_backend','disabled'), patch('services.agent.code_execution._container_runtime_available') as probe:
            self.assertFalse(sandbox_runtime_available())
            self.assertEqual(get_effective_sandbox_backend(),'disabled')
            probe.assert_not_called()

    def test_disabled_execution_returns_clear_result_without_running_a_process(self):
        with patch.object(settings,'code_sandbox_backend','disabled'), patch('subprocess.run') as run:
            result=CodeExecutionAgent()._execute_safe('print(1+1)')
            self.assertFalse(result['success'])
            self.assertEqual(result['backend'],'disabled')
            self.assertIn('代码审阅',result['error'])
            run.assert_not_called()


if __name__=='__main__': unittest.main()

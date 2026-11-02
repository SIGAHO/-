"""Keep old unit suites isolated from the new external model dependency.

Semantic review has its own unit tests and real-Ollama conversation evaluation.
These older suites use controlled generated replies and test other contracts.
"""
import unittest
from unittest.mock import patch


class ModelIsolatedCase(unittest.TestCase):
    def run(self,result=None):
        with patch('breaktail_v02.review_pragmatics',return_value={'applied':False,'hits':[],
                   'reason':'external semantic model isolated in unit test'}):
            return super().run(result)

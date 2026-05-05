import unittest

import DocGenAgent.src.tools.evaluate.BARTScore.D2T.gehrmann_rouge_opennmt.rouge_baselines.pyrouge.pyrouge.test
from pyrouge.test.Rouge155_test import PyrougeTest

loader = unittest.TestLoader()
suite = unittest.TestSuite()
suite.addTest(loader.loadTestsFromTestCase(PyrougeTest))
unittest.TextTestRunner().run(suite)

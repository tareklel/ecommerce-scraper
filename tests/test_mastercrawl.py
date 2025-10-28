import os
import json
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from ecommercecrawl.spiders.mastercrawl import MasterCrawl


class TestMasterCrawlUtils:
    """Tests for the utility methods of the MasterCrawl spider."""

    def test_generate_run_id(self):
        """
        Tests the _generate_run_id static method for correct format.
        """
        fixed_dt = datetime(2023, 10, 27, 10, 30, 5, 123456, tzinfo=timezone.utc)
        expected_id = "2023-10-27T10-30-05-123"

        with patch('ecommercecrawl.spiders.mastercrawl.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_dt
            run_id = MasterCrawl._generate_run_id()
        
        assert run_id == expected_id

    def test_generate_run_id_padding(self):
        """
        Tests that _generate_run_id correctly pads milliseconds.
        """
        # Test with milliseconds that require padding (e.g., 7ms -> 007)
        fixed_dt = datetime(2023, 10, 27, 10, 30, 5, 7000, tzinfo=timezone.utc)
        expected_id = "2023-10-27T10-30-05-007"

        with patch('ecommercecrawl.spiders.mastercrawl.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_dt
            run_id = MasterCrawl._generate_run_id()

        assert run_id == expected_id
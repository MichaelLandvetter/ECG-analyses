import unittest

from ecg_acquisition import SerialAcquisitionSource


class SerialAcquisitionParserTests(unittest.TestCase):
    def _collect(self, src: SerialAcquisitionSource):
        rows = []
        while True:
            sample = src._try_parse_next_sample()
            if sample is None:
                break
            if sample.size == 0:
                continue
            rows.append(sample.tolist())
        return rows

    def test_parses_header_and_rows_with_whitespace(self):
        src = SerialAcquisitionSource(sample_rate=250)
        src._buffer.extend(
            b"timestamp_ms,ecg_raw\n"
            b"  0 , 100 \n"
            b"4,101\n"
            b"8,-99\n"
        )
        rows = self._collect(src)
        self.assertEqual(rows, [[0.0, 100.0], [0.0, 101.0], [0.0, -99.0]])
        self.assertEqual(src._stream_format, "csv")
        self.assertIsNotNone(src._observed_sample_rate_hz)

    def test_parses_data_only_rows(self):
        src = SerialAcquisitionSource()
        src._buffer.extend(b"0,11\n5,12\n10,13\n")
        rows = self._collect(src)
        self.assertEqual(rows, [[0.0, 11.0], [0.0, 12.0], [0.0, 13.0]])

    def test_ignores_comments_and_empty_lines(self):
        src = SerialAcquisitionSource()
        src._buffer.extend(b"\n# boot banner\n# format: timestamp_ms,ecg_raw\n0,10\n")
        rows = self._collect(src)
        self.assertEqual(rows, [[0.0, 10.0]])
        self.assertEqual(src._stream_format, "csv")

    def test_malformed_rows_are_dropped_and_stream_continues(self):
        src = SerialAcquisitionSource()
        src._buffer.extend(b"0,10\nbad,row\n1,\n2,20\n")
        rows = self._collect(src)
        self.assertEqual(rows, [[0.0, 10.0], [0.0, 20.0]])
        self.assertGreaterEqual(src._dropped_malformed_lines, 2)

    def test_uint32_timestamp_rollover_is_handled(self):
        src = SerialAcquisitionSource(sample_rate=250)
        src._buffer.extend(b"4294967293,100\n1,101\n")
        rows = self._collect(src)
        self.assertEqual(rows, [[0.0, 100.0], [0.0, 101.0]])
        self.assertAlmostEqual(src._timing_delta_ms_ema, 4.0, places=2)
        self.assertIsNotNone(src._observed_sample_rate_hz)


if __name__ == "__main__":
    unittest.main()

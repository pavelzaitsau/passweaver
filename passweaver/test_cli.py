import unittest
from unittest import mock

import cli
import deps
import runner


class ParserTests(unittest.TestCase):
    def test_defaults(self):
        args = cli.build_parser().parse_args(['-f', 'caps'])
        self.assertEqual(args.files, ['caps'])
        self.assertEqual(args.time, 'std')
        self.assertEqual(args.version, 'v5.1')
        self.assertEqual(args.workload, 3)
        self.assertEqual(args.jobs, 1)
        self.assertFalse(args.yes)
        self.assertFalse(args.keep)
        self.assertFalse(args.fresh)
        self.assertFalse(args.list)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.rate)
        self.assertIsNone(args.outdir)
        self.assertIsNone(args.max_total)

    def test_files_required(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_time_choices(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['-f', 'c', '-t', 'forever'])

    def test_all_flags_parse(self):
        args = cli.build_parser().parse_args([
            '-f', 'a.pcap', 'b.pcap', '-t', 'deep', '-v', 'v5.1', '--rate', '620000',
            '--lang', 'pl', '--venue', 'Cafe', '--address', 'Main St',
            '-j', '4', '-o', 'out', '--max-total', '2h', '-w', '2',
            '--keep', '--fresh', '--list', '--dry-run', '--yes'])
        self.assertEqual(args.files, ['a.pcap', 'b.pcap'])
        self.assertEqual(args.time, 'deep')
        self.assertEqual(args.rate, 620000)
        self.assertEqual(args.lang, 'pl')
        self.assertEqual(args.venue, 'Cafe')
        self.assertEqual(args.address, 'Main St')
        self.assertEqual(args.jobs, 4)
        self.assertEqual(args.outdir, 'out')
        self.assertEqual(args.max_total, '2h')
        self.assertEqual(args.workload, 2)
        self.assertTrue(args.keep and args.fresh and args.list and args.dry_run and args.yes)

    def test_workload_choices(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['-f', 'c', '-w', '5'])

    def test_rate_is_int(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['-f', 'c', '--rate', 'fast'])


class ValidateTests(unittest.TestCase):
    def _args(self, **over):
        return cli.build_parser().parse_args(['-f', 'c'] + sum(
            ([k, str(v)] for k, v in over.items()), []))

    def test_rejects_other_engine(self):
        with self.assertRaises(runner.RunError):
            cli._validate(self._args(**{'-v': 'v4'}))

    def test_rejects_bad_duration(self):
        with self.assertRaises(ValueError):
            cli._validate(self._args(**{'--max-total': 'soon'}))

    def test_rejects_unknown_lang(self):
        with self.assertRaises(runner.RunError):
            cli._validate(self._args(**{'--lang': 'zz'}))

    def test_rejects_zero_jobs(self):
        with self.assertRaises(runner.RunError):
            cli._validate(self._args(**{'-j': '0'}))

    def test_rejects_nonpositive_rate(self):
        with self.assertRaises(runner.RunError):
            cli._validate(self._args(**{'--rate': '0'}))

    def test_accepts_valid_lang_and_duration(self):
        cli._validate(self._args(**{'--lang': 'pl', '--max-total': '90m'}))

    def test_lang_is_lowercased(self):
        args = cli.build_parser().parse_args(['-f', 'c', '--lang', 'PL'])
        self.assertEqual(args.lang, 'pl')
        cli._validate(args)

    def test_accepts_defaults(self):
        cli._validate(cli.build_parser().parse_args(['-f', 'c']))


class MainDispatchTests(unittest.TestCase):
    def test_main_returns_runner_code(self):
        with mock.patch.object(cli.runner, 'run', return_value=0) as run:
            code = cli.main(['-f', 'caps', '--yes'])
        self.assertEqual(code, 0)
        run.assert_called_once()

    def test_main_sets_interactive_flag(self):
        captured = {}

        def _capture(args, *a, **k):
            captured['args'] = args
            return 0
        with mock.patch.object(cli.runner, 'run', _capture):
            cli.main(['-f', 'caps', '--yes'])
        self.assertIn('interactive', vars(captured['args']))
        self.assertIsInstance(captured['args'].interactive, bool)

    def test_main_reports_runerror(self):
        with mock.patch.object(cli.runner, 'run', side_effect=runner.RunError('boom')):
            code = cli.main(['-f', 'caps'])
        self.assertEqual(code, 2)

    def test_main_reports_missing_dependency(self):
        with mock.patch.object(cli.runner, 'run',
                               side_effect=deps.MissingDependency('no hashcat')):
            code = cli.main(['-f', 'caps'])
        self.assertEqual(code, 2)

    def test_main_handles_interrupt(self):
        with mock.patch.object(cli.runner, 'run', side_effect=KeyboardInterrupt):
            code = cli.main(['-f', 'caps'])
        self.assertEqual(code, 130)

    def test_bad_engine_skips_run(self):
        with mock.patch.object(cli.runner, 'run') as run:
            code = cli.main(['-f', 'caps', '-v', 'v4'])
        self.assertEqual(code, 2)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

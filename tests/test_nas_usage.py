"""Synthetic domain inputs only; these are not NAS/API acceptance tests."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import importlib.util
from unittest import TestCase


class UsageBoundaryTests(TestCase):
    def test_freshness_compares_absolute_instants_across_dst_fold(self):
        from zoneinfo import ZoneInfo
        from nas_usage import Subject, UsageObservation

        zone = ZoneInfo("America/New_York")
        first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
        usage = UsageObservation(Subject("t", "account", "a", "s"), state="observed",
                                 source="synthetic", observed_at=first)
        self.assertEqual(usage.freshness(now=second, max_age=timedelta(minutes=30)), "stale")
        future = UsageObservation(usage.subject, state="observed", source="synthetic", observed_at=second)
        with self.assertRaises(ValueError):
            future.freshness(now=first, max_age=timedelta(hours=2))

    def test_only_bundled_reader_is_read_only_and_not_configured(self):
        import nas_usage

        self.assertTrue(hasattr(nas_usage, "NotConfiguredReader"), "offline adapter is missing")
        reader = nas_usage.NotConfiguredReader()
        self.assertIsInstance(reader, nas_usage.UsageReader)
        for kind in ("account", "group"):
            subject = nas_usage.Subject("t", kind, "1", "s")
            self.assertEqual(reader.read_usage(subject), nas_usage.UsageObservation(subject))
        self.assertFalse(hasattr(reader, "write_usage"))
        with self.assertRaises(ValueError):
            reader.read_usage(None)

    def test_display_never_presents_unknown_as_zero_or_stale_as_current(self):
        from nas_usage import Subject, UsageObservation

        self.assertTrue(callable(getattr(UsageObservation, "display", None)), "display is missing")
        subject = Subject("t", "account", "a", "s")
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock = dict(now=at, max_age=timedelta(seconds=5))
        for state, label in (("not_configured", "설정 안 됨"), ("unknown", "미수집")):
            display = UsageObservation(subject, state=state).display(**clock)
            self.assertEqual(display, dict(status=label, assigned="알 수 없음", used="알 수 없음", remaining="알 수 없음"))
        unlimited = UsageObservation(subject, state="observed", source="synthetic", observed_at=at, limit_kind="unlimited")
        self.assertEqual(unlimited.display(**clock), dict(status="최신 관측", assigned="무제한", used="알 수 없음", remaining="해당 없음 (무제한)"))
        finite = UsageObservation(subject, state="observed", source="synthetic", observed_at=at,
                                  limit_kind="limited", assigned_bytes=0, used_bytes=0, remaining_bytes=0)
        self.assertEqual(finite.display(**clock), dict(status="최신 관측", assigned="0 B", used="0 B", remaining="0 B"))
        stale = finite.display(now=at + timedelta(seconds=6), max_age=timedelta(seconds=5))
        self.assertEqual(stale, dict(status="오래된 관측", assigned="0 B (오래된 값)", used="0 B (오래된 값)", remaining="0 B (오래된 값)"))

    def test_freshness_uses_explicit_clock_and_age_without_erasing_old_values(self):
        from nas_usage import Subject, UsageObservation

        self.assertTrue(callable(getattr(UsageObservation, "freshness", None)), "freshness is missing")
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        usage = UsageObservation(Subject("t", "account", "a", "s"), state="observed",
                                 source="synthetic", observed_at=at, used_bytes=0)
        self.assertEqual(usage.freshness(now=at, max_age=timedelta(seconds=5)), "fresh")
        self.assertEqual(usage.freshness(now=at + timedelta(seconds=5), max_age=timedelta(seconds=5)), "fresh")
        self.assertEqual(usage.freshness(now=at + timedelta(seconds=6), max_age=timedelta(seconds=5)), "stale")
        self.assertEqual(usage.used_bytes, 0)
        for now, age in ((at - timedelta(seconds=1), timedelta(seconds=5)),
                         (at.replace(tzinfo=None), timedelta(seconds=5)),
                         (at, timedelta(seconds=-1)), (at, 5), ("now", timedelta(seconds=5))):
            with self.subTest(now=now, age=age), self.assertRaises(ValueError):
                usage.freshness(now=now, max_age=age)
        for state in ("not_configured", "unknown"):
            usage = UsageObservation(Subject("t", "account", "a", "s"), state=state)
            self.assertEqual(usage.freshness(now=at, max_age=timedelta(0)), state)

    def test_values_require_valid_observation_provenance_and_limit_semantics(self):
        from nas_usage import Subject, UsageObservation

        subject = Subject("t", "group", "g", "explicit-contract-scope")
        valid = dict(subject=subject, state="observed", source="synthetic-contract",
                     observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        usage = UsageObservation(**valid, limit_kind="limited", assigned_bytes=100,
                                 used_bytes=30, remaining_bytes=60)
        self.assertEqual((usage.assigned_bytes, usage.used_bytes, usage.remaining_bytes), (100, 30, 60))
        # Remaining is supplied, never manufactured as assigned minus used.
        self.assertIsNone(UsageObservation(**valid, limit_kind="limited", assigned_bytes=100, used_bytes=30).remaining_bytes)
        self.assertEqual(UsageObservation(**valid, limit_kind="unlimited", used_bytes=0).used_bytes, 0)
        self.assertIsNone(UsageObservation(**valid, limit_kind="unlimited").remaining_bytes)
        for update in (
            dict(state="fresh"), dict(limit_kind="infinite"), dict(source=None),
            dict(source=" "), dict(source=123), dict(observed_at=None),
            dict(observed_at=datetime(2026, 1, 1)), dict(observed_at="yesterday"),
            dict(limit_kind="limited"), dict(assigned_bytes=100),
            dict(limit_kind="unlimited", assigned_bytes=0),
            dict(limit_kind="unlimited", remaining_bytes=0), dict(remaining_bytes=1),
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                UsageObservation(**(valid | update))
        for field in ("assigned_bytes", "used_bytes", "remaining_bytes"):
            for value in (-1, True, 1.2, "0"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    UsageObservation(**(valid | dict(limit_kind="limited", assigned_bytes=100) | {field: value}))
        for state in ("not_configured", "unknown"):
            self.assertIsNone(UsageObservation(subject=subject, state=state).used_bytes)
            for update in (dict(used_bytes=0), dict(source="synthetic"),
                           dict(observed_at=valid["observed_at"]), dict(limit_kind="unlimited")):
                with self.subTest(state=state, update=update), self.assertRaises(ValueError):
                    UsageObservation(subject=subject, state=state, **update)

    def test_subject_requires_explicit_tenant_account_or_group_and_scope(self):
        from nas_usage import Subject, UsageObservation

        self.assertNotEqual(Subject("t", "account", "1", "s"), Subject("t", "group", "1", "s"))
        for field, value in (("tenant_id", ""), ("subject_id", " "), ("accounting_scope", None), ("kind", "volume"), ("subject_id", 1)):
            args = dict(tenant_id="t", kind="account", subject_id="1", accounting_scope="s")
            args[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Subject(**args)
        with self.assertRaises(ValueError):
            UsageObservation(subject="not a subject")

    def test_unconfigured_account_has_no_invented_measurements(self):
        self.assertIsNotNone(importlib.util.find_spec("nas_usage"), "usage boundary is missing")
        from nas_usage import Subject, UsageObservation

        usage = UsageObservation(subject=Subject("tenant-a", "account", "member-a", "scope-a"))
        self.assertEqual(usage.state, "not_configured")
        self.assertEqual(usage.limit_kind, "unknown")
        self.assertIsNone(usage.assigned_bytes)
        self.assertIsNone(usage.used_bytes)
        self.assertIsNone(usage.remaining_bytes)
        self.assertIsNone(usage.observed_at)
        self.assertIsNone(usage.source)
        with self.assertRaises(FrozenInstanceError):
            usage.used_bytes = 0

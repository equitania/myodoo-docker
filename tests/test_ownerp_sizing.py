"""
Tests for ownerp_sizing.py - the host-wide calculation of Odoo workers, memory
limits and PostgreSQL memory.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_sizing -v
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ownerp_sizing as sz  # noqa: E402


def inst(name, role, version=18, users=None, overrides=None, conf=None):
    return sz.Instance(name=name, version=version, role=role, users=users,
                       overrides=overrides or {}, db_container=None,
                       build_dir="", conf=conf if conf is not None else {})


def hw(cpus, gib):
    return sz.Hardware(cpus, gib * 1024)


class TestPlan(unittest.TestCase):
    def test_four_cpu_16gib_live_and_test(self):
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live"), inst("test-odoo", "test")])
        live, test = p.results
        self.assertEqual((p.budget_mib, p.need_mib, p.pg_total_mib), (9626, 3575, 4096))
        self.assertFalse(p.over_budget)
        self.assertEqual((live.workers, live.cron, live.processes), (5, 1, 7))
        self.assertEqual(live.odoo["workers"], "5")
        self.assertEqual(live.odoo["max_cron_threads"], "1")
        self.assertEqual(live.odoo["limit_memory_soft"], str(1189 * sz.MIB))
        self.assertEqual(live.odoo["limit_memory_hard"], str(1600 * sz.MIB))
        self.assertEqual(live.odoo["db_maxconn"], "16")
        self.assertEqual(live.pg, {"shared_buffers": "3072MB", "effective_cache_size": "9216MB",
                                   "max_connections": "132", "work_mem": "11MB",
                                   "maintenance_work_mem": "384MB"})
        self.assertEqual((test.workers, test.cron), (2, 1))
        self.assertEqual(test.odoo["limit_memory_soft"], str(512 * sz.MIB))
        self.assertEqual(test.odoo["limit_memory_hard"], str(1200 * sz.MIB))
        self.assertEqual(test.pg, {"shared_buffers": "1024MB", "effective_cache_size": "3072MB",
                                   "max_connections": "100", "work_mem": "5MB",
                                   "maintenance_work_mem": "128MB"})
        self.assertTrue(any("5 workers: 4 CPU -> 9 processes" in r and "3" in r
                            for r in live.reasons))

    def test_two_cpu_4gib_live_and_test_gets_minimal_staffing_and_a_warning(self):
        p = sz.compute_plan(hw(2, 4), [inst("live-odoo", "live"), inst("test-odoo", "test")])
        live, test = p.results
        self.assertTrue(p.over_budget)
        self.assertEqual((p.budget_mib, p.need_mib), (1639, 2275))
        self.assertEqual((live.workers, live.cron, test.workers, test.cron), (2, 1, 1, 1))
        self.assertEqual((live.odoo["limit_memory_soft"], live.odoo["limit_memory_hard"]),
                         ("629145600", "1677721600"))
        self.assertTrue(any("over budget" in w and "2275" in w and "1639" in w
                            for w in p.warnings))

    def test_two_cpu_4gib_live_only_squeezes_workers_and_fits(self):
        p = sz.compute_plan(hw(2, 4), [inst("live-odoo", "live")])
        self.assertFalse(p.over_budget)
        r = p.results[0]
        self.assertEqual(r.workers, 3)
        self.assertEqual(p.need_mib, 1625)
        self.assertEqual((r.odoo["limit_memory_soft"], r.odoo["limit_memory_hard"]),
                         ("629145600", "1677721600"))

    def test_eight_cpu_32gib_live_and_test(self):
        p = sz.compute_plan(hw(8, 32), [inst("live-odoo", "live"), inst("test-odoo", "test")])
        live = p.results[0]
        self.assertEqual((live.workers, live.cron), (12, 2))
        self.assertEqual(p.need_mib, 6175)
        self.assertEqual(live.odoo["limit_memory_soft"], str(1265 * sz.MIB))
        self.assertEqual(live.pg["max_connections"], "260")

    def test_live_limits_reach_the_cap_on_a_large_host(self):
        p = sz.compute_plan(hw(16, 128), [inst("live-odoo", "live")])
        r = p.results[0]
        self.assertEqual(r.workers, 31)
        self.assertEqual((r.odoo["limit_memory_soft"], r.odoo["limit_memory_hard"]),
                         ("2147483648", "2684354560"))

    def test_users_cap_workers_and_warn_when_the_host_is_smaller(self):
        r = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", users=12)]).results[0]
        self.assertEqual(r.workers, 2)
        self.assertEqual(r.odoo["limit_memory_soft"], str(2048 * sz.MIB))
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", users=4)])
        self.assertEqual(p.results[0].workers, 2)
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", users=60),
                                        inst("test-odoo", "test")])
        self.assertEqual(p.results[0].workers, 5)
        self.assertTrue(any("60 users need 10 workers, the host allows 5" in w
                            for w in p.warnings))

    def test_two_cpu_8gib_exceeds_the_cpu_rule_with_a_warning(self):
        p = sz.compute_plan(hw(2, 8), [inst("live-odoo", "live"), inst("test-odoo", "test")])
        live = p.results[0]
        self.assertEqual(live.workers, 2)
        self.assertEqual(live.odoo["limit_memory_soft"], str(750 * sz.MIB))
        self.assertEqual(live.odoo["limit_memory_hard"], str(1600 * sz.MIB))
        self.assertFalse(p.over_budget)
        self.assertTrue(any("6 processes > 5" in w for w in p.warnings))

    def test_demo_and_test_and_live_share_the_budget(self):
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live"), inst("test-odoo", "test"),
                                        inst("demo-odoo", "demo")])
        live = p.results[0]
        self.assertEqual(live.workers, 3)
        self.assertEqual(live.odoo["limit_memory_soft"], str(1470 * sz.MIB))
        self.assertEqual(live.odoo["limit_memory_hard"], str(1837 * sz.MIB))
        self.assertEqual(live.pg["shared_buffers"], "2457MB")
        demo = p.results[2]
        self.assertEqual((demo.workers, demo.cron), (1, 1))
        self.assertEqual(demo.odoo["limit_memory_soft"], str(384 * sz.MIB))

    def test_blockless_instance_counts_with_its_conf(self):
        p = sz.compute_plan(hw(4, 16), [
            inst("live-odoo", "live"),
            inst("old-odoo", None, conf={"workers": "3", "max_cron_threads": "2"})])
        live, old = p.results
        self.assertEqual(live.workers, 3)
        self.assertEqual(p.need_mib, 3575)
        self.assertFalse(old.sized)

    def test_blockless_odd_conf_values_never_raise(self):
        def others(conf):
            p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live"),
                                            inst("old-odoo", None, conf=conf)])
            return p.results[0].workers
        self.assertEqual(others({"workers": "0"}), 7)    # 1 process: 9 - 1 - 1
        self.assertEqual(others({"workers": "False"}), 3)  # shipped 3 + 2
        self.assertEqual(others({}), 3)

    def test_two_live_instances_split_the_remainder(self):
        p = sz.compute_plan(hw(4, 16), [inst("a-odoo", "live"), inst("b-odoo", "live")])
        self.assertEqual([r.workers for r in p.results], [3, 3])
        self.assertEqual(p.need_mib, 3250)

    def test_an_override_wins_and_a_budget_breaking_override_only_warns(self):
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", overrides={"workers": 8}),
                                        inst("test-odoo", "test")])
        self.assertEqual(p.results[0].odoo["workers"], "8")
        self.assertFalse(p.over_budget)
        p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", overrides={"workers": 40}),
                                        inst("test-odoo", "test")])
        self.assertEqual(p.results[0].odoo["workers"], "40")
        self.assertTrue(p.over_budget)
        self.assertTrue(any("Override" in w for w in p.warnings))

    def test_a_blockless_instance_is_never_squeezed_and_counts_with_its_conf(self):
        # doup never writes a blockless instance, so the plan must count it as it runs
        p = sz.compute_plan(hw(4, 6), [
            inst("live-odoo", "live"),
            inst("old-odoo", None, conf={"workers": "6", "max_cron_threads": "2"})])
        live, old = p.results
        self.assertEqual((old.workers, old.cron), (6, 2))
        self.assertEqual(p.budget_mib, 2970)
        self.assertEqual(p.need_mib, 4225)
        self.assertTrue(p.over_budget)
        self.assertTrue(any("4225" in w and "2970" in w for w in p.warnings), p.warnings)
        self.assertFalse(any("minimal staffing" in r for r in old.reasons))

    def test_a_soft_only_override_never_gives_hard_below_soft(self):
        p = sz.compute_plan(hw(8, 64), [
            inst("live-odoo", "live", overrides={"limit_memory_soft_mb": 3000})])
        live = p.results[0]
        soft = int(live.odoo["limit_memory_soft"]) // sz.MIB
        hard = int(live.odoo["limit_memory_hard"]) // sz.MIB
        self.assertEqual(soft, 3000)
        self.assertGreaterEqual(hard, soft)
        self.assertTrue(any("soft 3000 MiB / hard %d MiB" % hard in r for r in live.reasons),
                        live.reasons)


class TestOverrideRobustness(unittest.TestCase):
    def test_too_small_overrides_are_ignored_with_a_warning(self):
        base = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live"), inst("test-odoo", "test")])
        for key, value in (("workers", -1), ("max_cron_threads", 0), ("pg_max_connections", 0),
                           ("limit_memory_soft_mb", 10), ("db_maxconn", 0)):
            p = sz.compute_plan(hw(4, 16), [
                inst("live-odoo", "live", overrides={key: value}), inst("test-odoo", "test")])
            self.assertEqual(p.results[0].odoo, base.results[0].odoo, key)
            self.assertEqual(p.results[0].pg, base.results[0].pg, key)
            self.assertTrue(any(key in w and str(value) in w for w in p.warnings), key)

    def test_a_test_instance_takes_memory_overrides(self):
        p = sz.compute_plan(hw(4, 16), [
            inst("live-odoo", "live"),
            inst("test-odoo", "test", overrides={"limit_memory_soft_mb": 700,
                                                 "limit_memory_hard_mb": 1500})])
        self.assertEqual(p.results[1].odoo["limit_memory_soft"], str(700 * sz.MIB))
        self.assertEqual(p.results[1].odoo["limit_memory_hard"], str(1500 * sz.MIB))


class TestHelpers(unittest.TestCase):
    def test_odoo_keys_per_version(self):
        base = ("workers", "max_cron_threads", "limit_memory_soft", "limit_memory_hard", "db_maxconn")
        self.assertEqual(sz.odoo_keys(16), base)
        self.assertEqual(sz.odoo_keys(18), base + ("limit_memory_soft_gevent",
                                                   "limit_memory_hard_gevent", "db_maxconn_gevent"))
        self.assertEqual(sz.odoo_keys(19), base + ("db_maxconn_gevent",))
        self.assertEqual(sz.odoo_keys(20), sz.odoo_keys(19))
        self.assertEqual(sz.odoo_keys(18.0), sz.odoo_keys("18"))
        self.assertEqual(sz.odoo_keys("18"), sz.odoo_keys(18))
        self.assertEqual(sz.odoo_keys(""), base)
        self.assertEqual(sz.odoo_keys(None), base)
        self.assertEqual(sz.odoo_major(18.0), 18)
        self.assertIsNone(sz.odoo_major(""))

    def test_gevent_keys_in_the_plan(self):
        r = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", version=18)]).results[0]
        self.assertEqual(r.odoo["limit_memory_soft_gevent"], r.odoo["limit_memory_soft"])
        self.assertEqual(r.odoo["db_maxconn_gevent"], "16")
        r = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live", version=19)]).results[0]
        self.assertNotIn("limit_memory_soft_gevent", r.odoo)
        self.assertEqual(r.odoo["db_maxconn_gevent"], "16")

    def test_parse_conf_values(self):
        text = "[options]\n# c\n; c\nworkers = 3\nempty =\nname=a = b\n"
        self.assertEqual(sz.parse_conf_values(text),
                         {"workers": "3", "empty": "", "name": "a = b"})

    def test_pg_base_profile(self):
        self.assertEqual(sz.pg_base_profile(hw(2, 4)), "2cpu4gb")
        self.assertEqual(sz.pg_base_profile(hw(2, 8)), "2cpu8gb")
        self.assertEqual(sz.pg_base_profile(hw(4, 16)), "4cpu16gb")
        self.assertEqual(sz.pg_base_profile(hw(8, 32)), "8cpu32gb")

    def test_probe_hardware_reads_proc_under_a_root(self):
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "proc"))
            with open(os.path.join(root, "proc", "cpuinfo"), "w") as fh:
                fh.write("".join("processor\t: %d\nmodel name\t: x\n\n" % i for i in range(4)))
            with self.assertRaises(sz.SizingError):
                sz.probe_hardware(root)
            with open(os.path.join(root, "proc", "meminfo"), "w") as fh:
                fh.write("MemTotal:       16777216 kB\nMemFree: 1 kB\n")
            self.assertEqual(sz.probe_hardware(root), sz.Hardware(4, 16384))
        finally:
            shutil.rmtree(root)

    def test_instances_from_config_skips_parked_entries_unless_selected(self):
        root = tempfile.mkdtemp()
        try:
            a = os.path.join(root, "a")
            b = os.path.join(root, "b")
            os.makedirs(a)
            os.makedirs(b)
            with open(os.path.join(a, "odoo.conf"), "w") as fh:
                fh.write("[options]\nworkers = 4\n")
            containers = [
                {"container_name": "live-odoo", "dockerfile_path": a + "/", "odoo_version": "18.0",
                 "db_host": "live-db",
                 "sizing": {"profile": "live", "users": 30, "workers": 6, "bogus": 1}},
                {"container_name": "test-odoo", "dockerfile_path": b, "odoo_version": 18,
                 "active": False, "sizing": {"profile": "test"}},
            ]
            got = sz.instances_from_config(containers)
            self.assertEqual([i.name for i in got], ["live-odoo"])
            i = got[0]
            self.assertEqual((i.role, i.users, i.overrides, i.version, i.db_container),
                             ("live", 30, {"workers": 6}, 18, "live-db"))
            self.assertEqual(i.conf, {"workers": "4"})
            got = sz.instances_from_config(containers, selected="test-odoo")
            self.assertEqual([i.name for i in got], ["live-odoo", "test-odoo"])
            self.assertEqual(got[1].conf, {})
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

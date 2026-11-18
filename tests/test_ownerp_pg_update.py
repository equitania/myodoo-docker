"""
Tests for discovery, version, base and update choice of ownerp_pg_update.py.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_pg_update -v
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ownerp_pg_update as pg  # noqa: E402


class FakeRunner:
    """Maps a command prefix (tuple of argv items) to (code, output).

    The longest matching prefix wins; unknown commands fail with (1, "").
    Every call is recorded in `calls` as an argv list.
    """

    def __init__(self, answers=None):
        self.answers = {tuple(k): v for k, v in (answers or {}).items()}
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        best = None
        for prefix in self.answers:
            if tuple(argv[:len(prefix)]) == prefix and (best is None or len(prefix) > len(best)):
                best = prefix
        return self.answers[best] if best else (1, "")


def container(name, image, running=True, env=None, networks=None, labels=None,
              exposed=None, mounts=None):
    return {
        "Name": "/" + name,
        "State": {"Running": running},
        "Config": {
            "Image": image,
            "Env": ["%s=%s" % kv for kv in (env or {}).items()],
            "Labels": labels or {},
            "ExposedPorts": {p: {} for p in (exposed or [])},
        },
        "NetworkSettings": {"Networks": {n: {} for n in (networks or [])}},
        "Mounts": mounts or [],
    }


def psql(name, user):
    return ("docker", "exec", name, "psql", "-U", user, "-d", "postgres", "-Atc",
            "SHOW server_version")


DEBIAN_12 = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nID=debian\nVERSION_CODENAME=bookworm\n'


def host_answers(containers, extra=None):
    answers = {
        ("docker", "ps", "-aq"): (0, "\n".join("id%d" % i for i in range(len(containers)))),
        ("docker", "inspect"): (0, json.dumps(containers)),
    }
    answers.update(extra or {})
    return answers


def target(version=(16, 8), base=None, image="postgres:16.8", **kwargs):
    values = dict(name="live-db", image=image, inspect={}, version=version,
                  base=base, kind="compose", compose_file=None, compose_service=None,
                  db_user="postgres", pgdata=None, odoo=[], others=[],
                  shared=False, vector=False, foreign=False)
    values.update(kwargs)
    return pg.PgTarget(**values)


BOOKWORM = pg.Base("glibc 2.36", "bookworm")


class ServerVersionTest(unittest.TestCase):
    def test_version_is_read_from_the_server_not_the_tag(self):
        pgc = container("live-db", "postgres:16", exposed=["5432/tcp"])
        run = FakeRunner(host_answers([pgc], {
            psql("live-db", "postgres"): (0, "16.8 (Debian 16.8-1.pgdg120+1)\n"),
            ("docker", "exec", "live-db", "cat"): (0, DEBIAN_12),
            ("docker", "exec", "live-db", "sh"): (0, "ldd (Debian GLIBC 2.36-9+deb12u10) 2.36"),
        }))
        found = pg.discover(run, {})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].version, (16, 8))
        self.assertEqual(found[0].base, BOOKWORM)
        self.assertEqual(found[0].db_user, "postgres")

    def test_db_user_falls_back_in_order(self):
        pgc = container("live-db", "postgres:16", env={"POSTGRES_USER": "wrong"})
        cfg = {"containers": [{"container_name": "live-odoo", "db_host": "live-db",
                               "db_user": "ownerp"}]}
        run = FakeRunner({
            psql("live-db", "wrong"): (2, "FATAL: role does not exist"),
            psql("live-db", "ownerp"): (0, "16.8\n"),
            psql("live-db", "postgres"): (0, "16.8\n"),
        })
        self.assertEqual(pg.db_user_for(pgc, cfg, None, run), "ownerp")
        users = [c[5] for c in run.calls]
        self.assertEqual(users, ["wrong", "ownerp"])
        # CLI value wins when it works
        self.assertEqual(pg.db_user_for(pgc, cfg, "postgres", FakeRunner(run.answers)), "postgres")
        # nothing works -> None
        self.assertIsNone(pg.db_user_for(pgc, cfg, None, FakeRunner()))

    def test_server_version_parses_major_minor(self):
        run = FakeRunner({psql("x", "u"): (0, "17.2 (Debian 17.2-1.pgdg120+1)\n")})
        self.assertEqual(pg.server_version("x", "u", run), (17, 2))
        self.assertIsNone(pg.server_version("x", "other", run))


class BaseTest(unittest.TestCase):
    def test_alpine_uses_musl_with_version_id(self):
        run = FakeRunner({
            ("docker", "exec", "x", "cat"): (0, "ID=alpine\nVERSION_ID=3.20.3\n"),
        })
        self.assertEqual(pg.base_of_container("x", run), pg.Base("musl 3.20.3", None))

    def test_image_base_from_one_run(self):
        out = DEBIAN_12 + "ldd (Debian GLIBC 2.36-9+deb12u10) 2.36\n"
        run = FakeRunner({("docker", "run", "--rm", "--entrypoint", "sh"): (0, out)})
        self.assertEqual(pg.base_of_image("postgres:16.9-bookworm", run), BOOKWORM)
        self.assertIsNone(pg.base_of_image("postgres:nope", FakeRunner()))


class DiscoverTest(unittest.TestCase):
    def test_compose_label_decides_kind(self):
        labels = {"com.docker.compose.project.config_files": "/srv/live/compose.yml,/x.yml",
                  "com.docker.compose.service": "db"}
        compose = container("live-db", "postgres:16", labels=labels)
        legacy = container("test-db", "postgres:16")
        run = FakeRunner(host_answers([compose, legacy], {
            psql("live-db", "postgres"): (0, "16.8\n"),
            psql("test-db", "postgres"): (0, "16.8\n"),
        }))
        by_name = {t.name: t for t in pg.discover(run, {})}
        self.assertEqual(by_name["live-db"].kind, "compose")
        self.assertEqual(by_name["live-db"].compose_file, "/srv/live/compose.yml")
        self.assertEqual(by_name["live-db"].compose_service, "db")
        self.assertEqual(by_name["test-db"].kind, "legacy")
        self.assertIsNone(by_name["test-db"].compose_file)

    def test_pairing_by_env_and_by_yaml_db_host(self):
        mounts = [{"Source": "/srv/pg", "Destination": "/var/lib/postgresql/data"}]
        pgc = container("live-db", "postgres-pgvector:16.8", networks=["live"], mounts=mounts)
        other_pg = container("test-db", "postgres:16", networks=["test"])
        odoo = container("live-odoo", "odoo/live", networks=["live"], exposed=["8069/tcp"],
                         env={"HOST": "live-db"})
        helper = container("live-report", "ci/fr-api", networks=["live"])
        cfg = {"containers": [
            {"container_name": "live-odoo", "db_host": "live-db",
             "sizing": {"profile": "live", "workers": 6}},
            {"container_name": "demo-odoo", "db_host": "live-db", "database_name": "demo"},
        ]}
        run = FakeRunner(host_answers([pgc, other_pg, odoo, helper], {
            psql("live-db", "postgres"): (0, "16.8\n"),
            psql("test-db", "postgres"): (0, "16.8\n"),
        }))
        by_name = {t.name: t for t in pg.discover(run, cfg)}
        live = by_name["live-db"]
        self.assertEqual({o.name for o in live.odoo}, {"live-odoo", "demo-odoo"})
        env_found = next(o for o in live.odoo if o.name == "live-odoo")
        yaml_only = next(o for o in live.odoo if o.name == "demo-odoo")
        self.assertTrue(env_found.running)
        self.assertEqual(env_found.workers, 6)
        self.assertTrue(env_found.has_sizing)
        self.assertFalse(yaml_only.running)
        self.assertFalse(yaml_only.has_sizing)
        self.assertEqual(yaml_only.database, "demo")
        self.assertTrue(live.shared)
        self.assertTrue(live.vector)
        self.assertFalse(live.foreign)
        self.assertEqual(live.pgdata, "/srv/pg")
        self.assertEqual(live.others, ["live-report"])
        self.assertEqual(by_name["test-db"].odoo, [])
        self.assertFalse(by_name["test-db"].shared)

    def test_stopped_postgres_is_skipped_and_foreign_flagged(self):
        stopped = container("old-db", "postgres:16", running=False)
        foreign = container("bitnami-db", "bitnami/postgresql:16", exposed=["5432/tcp"])
        run = FakeRunner(host_answers([stopped, foreign], {
            psql("bitnami-db", "postgres"): (0, "16.2\n"),
        }))
        found = pg.discover(run, {})
        self.assertEqual([t.name for t in found], ["bitnami-db"])
        self.assertTrue(found[0].foreign)

    def test_no_docker_answer_gives_no_targets(self):
        self.assertEqual(pg.discover(FakeRunner(), {}), [])


class HubTagsTest(unittest.TestCase):
    def test_follows_next_and_collects_names(self):
        pages = {
            pg.HUB_TAGS_URL % 16: json.dumps({"results": [{"name": "16.8"}],
                                              "next": "https://hub/page2"}),
            "https://hub/page2": json.dumps({"results": [{"name": "16.9-bookworm"}],
                                             "next": None}),
        }
        self.assertEqual(pg.hub_tags(16, pages.get), {"16.8", "16.9-bookworm"})

    def test_first_page_failure_is_none(self):
        self.assertIsNone(pg.hub_tags(16, lambda url: None))
        self.assertIsNone(pg.hub_tags(16, lambda url: "not json"))

    def test_later_page_failure_keeps_what_we_have(self):
        first = json.dumps({"results": [{"name": "16.8"}], "next": "https://hub/p2"})
        pages = {pg.HUB_TAGS_URL % 16: first}
        self.assertEqual(pg.hub_tags(16, pages.get), {"16.8"})

    def test_at_most_ten_pages(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return json.dumps({"results": [], "next": "https://hub/again"})

        pg.hub_tags(16, fetch)
        self.assertEqual(len(calls), 10)


class ChooseTest(unittest.TestCase):
    def test_choose_pins_the_running_base(self):
        t = target(base=BOOKWORM, image="postgres:16.8")
        c = pg.choose(t, {"16.16", "16.16-bookworm", "16.16-trixie", "16.9"}, None)
        self.assertEqual(c.tag, "postgres:16.16-bookworm")
        self.assertEqual(c.version, (16, 16))
        self.assertIsNone(c.blocked)

    def test_choose_falls_back_to_highest_pinned_tag(self):
        t = target(base=BOOKWORM)
        c = pg.choose(t, {"16.16", "16.16-trixie", "16.15-bookworm", "16.14-bookworm"}, None)
        self.assertEqual(c.tag, "postgres:16.15-bookworm")

    def test_choose_uses_plain_tag_and_says_so_when_nothing_is_pinned(self):
        t = target(base=BOOKWORM)
        c = pg.choose(t, {"16.9", "16.8"}, None)
        self.assertEqual(c.tag, "postgres:16.9")
        self.assertIn("confirm the base", c.note)

    def test_choose_without_codename_keeps_the_tag_suffix(self):
        t = target(base=pg.Base("musl 3.20.3", None), image="postgres:16.8-alpine")
        c = pg.choose(t, {"16.9-alpine", "16.9", "16.10-alpine"}, None)
        self.assertEqual(c.tag, "postgres:16.10-alpine")

    def test_choose_refuses_another_major(self):
        t = target(base=BOOKWORM)
        c = pg.choose(t, {"17.2-bookworm"}, "17.2")
        self.assertIsNone(c.tag)
        self.assertEqual(c.blocked, "major upgrades are not supported")

    def test_choose_honours_an_explicit_target(self):
        t = target(base=BOOKWORM)
        c = pg.choose(t, {"16.12-bookworm", "16.16-bookworm"}, "16.12")
        self.assertEqual(c.tag, "postgres:16.12-bookworm")
        # explicit suffix is used verbatim; works without registry access too
        c = pg.choose(t, None, "16.12-trixie")
        self.assertEqual(c.tag, "postgres:16.12-trixie")

    def test_choose_current(self):
        t = target(version=(16, 16), base=BOOKWORM, image="postgres:16.16-bookworm")
        c = pg.choose(t, {"16.16-bookworm", "16.15-bookworm"}, None)
        self.assertIsNone(c.tag)
        self.assertEqual(c.note, "current")
        self.assertIsNone(c.blocked)

    def test_choose_for_pgvector_keeps_our_repository(self):
        t = target(base=BOOKWORM, image="postgres-pgvector:16.8", vector=True)
        c = pg.choose(t, {"16.16-bookworm"}, None)
        self.assertEqual(c.tag, "postgres-pgvector:16.16-bookworm")

    def test_overview_without_registry(self):
        c = pg.choose(target(base=BOOKWORM), None, None)
        self.assertIsNone(c.tag)
        self.assertEqual(c.note, "unknown (no registry access)")
        self.assertIsNone(c.blocked)

    def test_foreign_image_is_blocked(self):
        t = target(base=BOOKWORM, image="bitnami/postgresql:16.2", foreign=True)
        c = pg.choose(t, {"16.16-bookworm"}, None)
        self.assertIsNone(c.tag)
        self.assertEqual(c.blocked, "image bitnami/postgresql:16.2 is not maintained by this tool")

    def test_unknown_running_version_is_blocked(self):
        c = pg.choose(target(version=None, base=BOOKWORM), {"16.16-bookworm"}, None)
        self.assertIsNotNone(c.blocked)


def _hardware():
    return pg._need("ownerp_sizing").Hardware(cpus=8, ram_mib=16384)


def pg_settings(values):
    return (0, "\n".join("%s|%s" % kv for kv in values.items()) + "\n")


PSQL_SETTINGS = ("docker", "exec", "live-db", "psql", "-U", "postgres", "-d", "postgres", "-tAc")


def odoo_info(**kw):
    values = dict(name="live-odoo", image="eq/odoo:18", running=True, version="18.0",
                  database="live_db", workers=4, has_sizing=True)
    values.update(kw)
    return pg.OdooInfo(**values)


TODAY = datetime.date(2026, 11, 18)
NO_SIZING = pg.SizingView({}, {}, {}, None)
UPDATE_16 = pg.Choice("postgres:16.16-bookworm", (16, 16), "16.8 -> 16.16 (base bookworm kept)")
CURRENT = pg.Choice(None, None, "current")


def rec_ids(t, c, sizing=NO_SIZING, unlisted=(), today=TODAY, collation=()):
    return [r.id for r in pg.recommend(t, c, sizing, list(unlisted), today, list(collation))]


class SizingViewTest(unittest.TestCase):
    CFG = {"containers": [{"container_name": "live-odoo", "db_host": "live-db",
                           "sizing": {"profile": "live"}}]}

    def test_shared_container_keeps_sizing_out(self):
        t = target(base=BOOKWORM, shared=True, odoo=[odoo_info(), odoo_info(name="x-odoo")])
        view = pg.sizing_view(t, self.CFG, "live", FakeRunner(), _hardware())
        self.assertEqual(view.skipped, "shared container")
        self.assertEqual(view.differs, {})
        ids = rec_ids(t, CURRENT, view)
        self.assertNotIn("sizing_differs", ids)
        self.assertIn("shared_db", ids)

    def test_differing_value_is_reported_with_both_sides(self):
        run = FakeRunner({PSQL_SETTINGS: pg_settings({"shared_buffers": "128MB"})})
        view = pg.sizing_view(target(base=BOOKWORM), self.CFG, "live", run, _hardware())
        self.assertIsNone(view.skipped)
        self.assertIn("shared_buffers", view.differs)
        cur, rec = view.differs["shared_buffers"]
        self.assertEqual(cur, "128MB")
        self.assertEqual(rec, view.recommended["shared_buffers"])

    def test_equal_sizes_in_other_units_do_not_differ(self):
        sizing = pg._need("ownerp_sizing")
        first = pg.sizing_view(target(base=BOOKWORM), self.CFG, "live",
                               FakeRunner({PSQL_SETTINGS: pg_settings({"shared_buffers": "1MB"})}),
                               _hardware())
        rec = first.recommended["shared_buffers"]
        in_kb = "%dkB" % (sizing.pg_size_mib(rec) * 1024)
        self.assertNotEqual(rec, in_kb)
        run = FakeRunner({PSQL_SETTINGS: pg_settings({"shared_buffers": in_kb})})
        view = pg.sizing_view(target(base=BOOKWORM), self.CFG, "live", run, _hardware())
        self.assertNotIn("shared_buffers", view.differs)

    def test_no_block_uses_the_role_and_unknown_role_is_skipped(self):
        run = FakeRunner({PSQL_SETTINGS: pg_settings({"shared_buffers": "128MB"})})
        view = pg.sizing_view(target(base=BOOKWORM), {}, "test", run, _hardware())
        self.assertIsNone(view.skipped)
        self.assertTrue(view.recommended)
        view = pg.sizing_view(target(base=BOOKWORM), {}, None, run, _hardware())
        self.assertEqual(view.skipped, "role unknown")

    def test_entry_without_sizing_block_is_not_counted_twice(self):
        sizing = pg._need("ownerp_sizing")
        cfg = {"containers": [{"container_name": "live-odoo", "db_host": "live-db"}]}
        seen = []
        real = sizing.compute_plan

        def recorder(hw, instances):
            seen.append([(i.name, i.db_container, i.role) for i in instances])
            return real(hw, instances)

        sizing.compute_plan = recorder
        try:
            run = FakeRunner({PSQL_SETTINGS: pg_settings({"shared_buffers": "128MB"})})
            view = pg.sizing_view(target(base=BOOKWORM), cfg, "live", run, _hardware())
        finally:
            sizing.compute_plan = real
        self.assertEqual(seen, [[("live-odoo", "live-db", "live")]])
        self.assertIsNone(view.skipped)
        # entry without a profile and no usable role: unknown
        view = pg.sizing_view(target(base=BOOKWORM), cfg, None, run, _hardware())
        self.assertEqual(view.skipped, "role unknown")

    def test_unreadable_current_values_are_skipped(self):
        view = pg.sizing_view(target(base=BOOKWORM), self.CFG, "live", FakeRunner(), _hardware())
        self.assertEqual(view.skipped, "current values unreadable")
        self.assertEqual(view.differs, {})


class RecommendTest(unittest.TestCase):
    def test_recommendation_order_and_ids(self):
        t = target(base=BOOKWORM, kind="legacy")
        view = pg.SizingView({"shared_buffers": "4GB"}, {"shared_buffers": "1GB"},
                             {"shared_buffers": ("1GB", "4GB")}, None)
        recs = pg.recommend(t, UPDATE_16, view, [], TODAY, [])
        self.assertEqual([r.id for r in recs], ["patch_update", "convert_compose", "sizing_differs"])
        self.assertIn("postgres:16.16-bookworm", recs[0].text)
        self.assertIn("stays on bookworm", recs[0].text)
        self.assertIn("shared_buffers 1GB -> 4GB", recs[2].text)

    def test_full_order(self):
        t = target(version=(14, 3), image="postgres:14.3", base=BOOKWORM, kind="legacy",
                   shared=True, foreign=True)
        blocked = pg.Choice(None, None, "x", blocked="foreign")
        self.assertEqual(rec_ids(t, blocked, unlisted=["a"], collation=["live_db"]),
                         ["foreign_image", "major_eol", "convert_compose", "shared_db",
                          "backup_missing", "collation_mismatch"])
        both = target(base=BOOKWORM, kind="legacy", shared=True)
        view = pg.SizingView({"work_mem": "8MB"}, {"work_mem": "4MB"},
                             {"work_mem": ("4MB", "8MB")}, None)
        self.assertEqual(rec_ids(both, UPDATE_16, view, ["a"], collation=["d"]),
                         ["patch_update", "convert_compose", "sizing_differs", "shared_db",
                          "backup_missing", "collation_mismatch"])

    def test_major_eol_on_and_after_the_month(self):
        t14 = target(version=(14, 3), image="postgres:14.3", base=BOOKWORM)
        self.assertIn("major_eol", rec_ids(t14, CURRENT))
        self.assertIn("major_eol", rec_ids(t14, CURRENT, today=datetime.date(2027, 3, 1)))
        self.assertNotIn("major_eol", rec_ids(t14, CURRENT, today=datetime.date(2026, 10, 31)))
        text = [r.text for r in pg.recommend(t14, CURRENT, NO_SIZING, [], TODAY, [])
                if r.id == "major_eol"][0]
        self.assertIn("11/2026", text)
        self.assertIn("plan a major upgrade separately", text)
        t15 = target(version=(15, 6), image="postgres:15.6", base=BOOKWORM)
        self.assertNotIn("major_eol", rec_ids(t15, CURRENT))
        t99 = target(version=(99, 1), image="postgres:99.1", base=BOOKWORM)
        self.assertNotIn("major_eol", rec_ids(t99, CURRENT))

    def test_nothing_to_do_has_no_recommendation(self):
        self.assertEqual(rec_ids(target(base=BOOKWORM), CURRENT), [])

    def test_unpinned_text_has_no_stays_on(self):
        c = pg.Choice("postgres:16.16", (16, 16), "n")
        recs = pg.recommend(target(base=None), c, NO_SIZING, [], TODAY, [])
        self.assertNotIn("stays on", recs[0].text)


class BackupRoutesTest(unittest.TestCase):
    def test_backup_routes_split(self):
        cfg = {"databases": [{"name": "a", "sql_container": "live-db"},
                             {"name": "b", "sql_container": "other-db"}]}
        self.assertEqual(pg.backup_routes(["a", "b"], cfg, "live-db"), (["a"], ["b"]))
        self.assertEqual(pg.backup_routes(["a", "b"], None, "live-db"), ([], ["a", "b"]))


class CollationTest(unittest.TestCase):
    def test_old_major_is_not_asked(self):
        run = FakeRunner()
        self.assertEqual(pg.collation_mismatches(target(version=(14, 3), base=BOOKWORM), run), [])
        self.assertEqual(run.calls, [])

    def test_new_major_lists_mismatched_databases(self):
        run = FakeRunner({("docker", "exec", "live-db", "psql"): (0, "live_db\nother\n")})
        self.assertEqual(pg.collation_mismatches(target(base=BOOKWORM), run), ["live_db", "other"])
        self.assertIn("pg_database_collation_actual_version", run.calls[0][-1])
        self.assertEqual(pg.collation_mismatches(target(base=BOOKWORM), FakeRunner()), [])


def sample_rows():
    live = target(base=BOOKWORM, kind="legacy", odoo=[odoo_info()])
    test = target(name="test-db", version=(16, 16), image="postgres:16.16-bookworm",
                  base=BOOKWORM, odoo=[odoo_info(name="test-odoo", database="test_db",
                                                 workers=None, has_sizing=False)])
    demo = target(name="demo-db", version=(15, 6), image="postgres:15.6", base=BOOKWORM,
                  kind="legacy", shared=True,
                  odoo=[odoo_info(name="demo-odoo", version=None, database=None, workers=None),
                        odoo_info(name="demo2-odoo", version=None, database=None, workers=None)])
    unknown = pg.Choice(None, None, "unknown (no registry access)")
    return [(live, UPDATE_16, pg.recommend(live, UPDATE_16, NO_SIZING, [], TODAY, [])),
            (test, CURRENT, []),
            (demo, unknown, pg.recommend(demo, unknown, NO_SIZING, [], TODAY, []))]


class OverviewTest(unittest.TestCase):
    def test_overview_text_shows_pairing(self):
        text = pg.render_overview(sample_rows())
        lines = text.splitlines()
        self.assertEqual(lines[0].split(), ["#", "PostgreSQL", "Version", "Update", "Kind", "Odoo"])
        live_line = [l for l in lines if "live-db" in l and "live-odoo" in l][0]
        self.assertIn("live-odoo (18.0, db live_db, 4 workers)", live_line)
        self.assertIn("16.8", live_line)
        self.assertIn("16.16-bookworm", live_line)
        self.assertIn("legacy", live_line)
        test_line = [l for l in lines if "test-db" in l][0]
        self.assertIn("test-odoo (18.0, db test_db)", test_line)
        self.assertIn("current", test_line)
        demo_line = [l for l in lines if "demo-db" in l][0]
        self.assertIn("demo-odoo, demo2-odoo (shared)", demo_line)
        self.assertIn(" 2  nothing to do", text)
        self.assertIn("Select", text)

    def test_odoo_cell_omits_unknown_parts(self):
        no_workers = target(name="x-db", odoo=[odoo_info(workers=None)])
        bare = target(name="z-db", odoo=[odoo_info(name="bare", version=None, database=None,
                                                   workers=None)])
        none = target(name="y-db", odoo=[])
        text = pg.render_overview([(no_workers, CURRENT, []), (bare, CURRENT, []),
                                   (none, CURRENT, [])])
        self.assertIn("live-odoo (18.0, db live_db)", text)
        z_line = [l for l in text.splitlines() if "z-db" in l][0]
        self.assertTrue(z_line.rstrip().endswith("bare"))
        y_line = [l for l in text.splitlines() if "y-db" in l][0]
        self.assertTrue(y_line.rstrip().endswith("-"))

    def test_json_carries_version_update_recommendation_and_odoo(self):
        doc = pg.overview_json(sample_rows())
        self.assertEqual(doc["tool"], "ownerp_pg_update")
        self.assertEqual(doc["version"], pg.SCRIPT_VERSION)
        live, test, demo = doc["containers"]
        self.assertEqual(live["name"], "live-db")
        self.assertEqual(live["image"], "postgres:16.8")
        self.assertEqual(live["version"], "16.8")
        self.assertEqual(live["base"], {"libc": "glibc 2.36", "codename": "bookworm"})
        self.assertEqual(live["kind"], "legacy")
        self.assertIsNone(live["compose_file"])
        self.assertEqual(live["update"], {"available": True, "image": "postgres:16.16-bookworm",
                                          "version": "16.16", "note": UPDATE_16.note,
                                          "blocked": None,
                                          "release_notes": [
                                              "https://www.postgresql.org/docs/release/16.%d/" % k
                                              for k in range(16, 8, -1)]})
        self.assertEqual(live["odoo"], [{"name": "live-odoo", "image": "eq/odoo:18",
                                         "running": True, "version": "18.0",
                                         "database": "live_db", "workers": 4,
                                         "has_sizing": True}])
        self.assertEqual(live["other_clients"], [])
        self.assertFalse(live["shared"])
        self.assertEqual([r["id"] for r in live["recommendations"]],
                         ["patch_update", "convert_compose"])
        self.assertTrue(all(set(r) == {"id", "text"} for r in live["recommendations"]))
        self.assertFalse(test["update"]["available"])
        self.assertIsNone(test["update"]["image"])
        self.assertIsNone(test["update"]["version"])
        self.assertEqual(test["recommendations"], [])
        self.assertTrue(demo["shared"])
        json.dumps(doc)

    def test_json_without_version_or_base(self):
        doc = pg.overview_json([(target(version=None, base=None), CURRENT, [])])
        c = doc["containers"][0]
        self.assertIsNone(c["version"])
        self.assertIsNone(c["base"])


class SelectionTest(unittest.TestCase):
    def test_parse_selection(self):
        self.assertEqual(pg.parse_selection("1,3", 3, {1}), [1, 3])
        self.assertEqual(pg.parse_selection("1 3", 3, {1}), [1, 3])
        self.assertEqual(pg.parse_selection("3,1,3", 3, {1}), [3, 1])
        self.assertEqual(pg.parse_selection("a", 3, {1, 3}), [1, 3])
        self.assertEqual(pg.parse_selection("", 3, {1}), [])
        self.assertIsNone(pg.parse_selection("4", 3, set()))
        self.assertIsNone(pg.parse_selection("0", 3, set()))
        self.assertIsNone(pg.parse_selection("x", 3, set()))
        self.assertIsNone(pg.parse_selection("1,x", 3, set()))


class SiblingTest(unittest.TestCase):
    def test_load_sibling(self):
        self.assertIsNotNone(pg.load_sibling("ownerp_migrate"))
        self.assertIsNone(pg.load_sibling("no_such_script"))


IMAGE = {
    "Config": {
        "Env": ["PATH=/usr/local/bin:/usr/bin", "PG_MAJOR=16", "GOSU_VERSION=1.17",
                "LANG=en_US.utf8"],
        "Labels": {"org.opencontainers.image.title": "postgres"},
        "Cmd": ["postgres"],
        "Entrypoint": ["docker-entrypoint.sh"],
    }
}

INSPECT_LEGACY = {
    "Id": "a" * 64,
    "Name": "/live-db",
    "Config": {
        "User": "",
        "Env": ["PATH=/usr/local/bin:/usr/bin", "PG_MAJOR=16", "GOSU_VERSION=1.17",
                "LANG=en_US.utf8", "POSTGRES_PASSWORD=pa$word", "POSTGRES_USER=ownerp"],
        "Labels": {"org.opencontainers.image.title": "postgres"},
        "Cmd": ["postgres"],
        "Entrypoint": ["docker-entrypoint.sh"],
        "Healthcheck": None,
    },
    "HostConfig": {
        "RestartPolicy": {"Name": "always", "MaximumRetryCount": 0},
        "ShmSize": 67108864,
        "Memory": 0,
        "NanoCpus": 0,
        "PortBindings": {},
        "ExtraHosts": None,
        "Dns": [],
        "DnsSearch": [],
        "LogConfig": {"Type": "json-file", "Config": {}},
        "Links": None,
        "VolumesFrom": None,
        "Devices": [],
        "CapAdd": None,
        "CapDrop": None,
        "Privileged": False,
        "SecurityOpt": None,
        "Tmpfs": {},
        "Ulimits": [],
        "PidMode": "",
        "IpcMode": "private",
        "UTSMode": "",
        "NetworkMode": "live-db-net",
    },
    "Mounts": [{"Type": "bind", "Source": "/opt/pg/live-db",
                "Destination": "/var/lib/postgresql/data", "RW": True}],
    "NetworkSettings": {"Networks": {"live-db-net": {
        "Aliases": ["live-db", "a" * 12, "db"], "IPAMConfig": None}}},
}


def legacy(**changes):
    """A deep copy of INSPECT_LEGACY; a double underscore in a key descends one level."""
    doc = json.loads(json.dumps(INSPECT_LEGACY))
    for dotted, value in changes.items():
        node = doc
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return doc


def convert(inspect=None, **kwargs):
    return pg.compose_from_inspect(inspect or INSPECT_LEGACY, IMAGE,
                                   "postgres:16.16-bookworm", "ownerp", **kwargs)


TWO_SERVICES = """services:
  postgres:
    image: postgres:16.15-bookworm
    container_name: live-db
    build:
      context: ./pgvector
      args:
        PG_VERSION: "16.15-bookworm"
  adminer:
    image: adminer:4
    restart: always
"""


class ComposeFromInspectTest(unittest.TestCase):
    def test_roundtrip_of_a_plain_legacy_container(self):
        doc, blockers = convert()
        svc = doc["services"]["postgres"]
        self.assertEqual(blockers, [])
        self.assertEqual(svc["image"], "postgres:16.16-bookworm")
        self.assertEqual(svc["container_name"], "live-db")
        self.assertEqual(svc["restart"], "always")
        self.assertEqual(svc["volumes"], ["/opt/pg/live-db:/var/lib/postgresql/data"])
        self.assertEqual(svc["environment"]["PGDATA"], "/var/lib/postgresql/data")
        self.assertEqual(doc["networks"], {"live-db-net": {"external": True}})
        self.assertEqual(svc["networks"], {"live-db-net": {"aliases": ["db"]}})
        self.assertNotIn("command", svc)
        self.assertNotIn("entrypoint", svc)
        self.assertNotIn("shm_size", svc)
        self.assertNotIn("user", svc)

    def test_image_environment_is_not_copied(self):
        doc, _ = convert()
        env = doc["services"]["postgres"]["environment"]
        for key in ("PG_MAJOR", "PATH", "GOSU_VERSION", "LANG"):
            self.assertNotIn(key, env)
        self.assertEqual(env["POSTGRES_USER"], "ownerp")

    def test_dollar_in_environment_is_escaped(self):
        doc, _ = convert()
        self.assertEqual(doc["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"],
                         "pa$$word")

    def test_pgdata_follows_the_containers_own_setting(self):
        inspect = legacy(Mounts=[{"Type": "bind", "Source": "/opt/pg/x",
                                  "Destination": "/data/pg/", "RW": True}])
        inspect["Config"]["Env"].append("PGDATA=/data/pg/")
        doc, blockers = convert(inspect)
        svc = doc["services"]["postgres"]
        self.assertEqual(blockers, [])
        self.assertEqual(svc["environment"]["PGDATA"], "/data/pg")
        self.assertEqual(svc["volumes"], ["/opt/pg/x:/data/pg"])

    def test_read_only_mount_and_other_settings(self):
        inspect = legacy(
            Mounts=[{"Type": "bind", "Source": "/opt/pg/live-db",
                     "Destination": "/var/lib/postgresql/data/", "RW": True},
                    {"Type": "bind", "Source": "/etc/ssl/pg", "Destination": "/certs",
                     "RW": False}],
            HostConfig__ShmSize=1073741824, HostConfig__Memory=2147483648,
            HostConfig__NanoCpus=1500000000,
            HostConfig__RestartPolicy={"Name": "on-failure", "MaximumRetryCount": 3},
            HostConfig__PortBindings={"5432/tcp": [{"HostIp": "127.0.0.1",
                                                    "HostPort": "5433"}]},
            HostConfig__ExtraHosts=["registry:192.0.2.5"],
            HostConfig__Dns=["192.0.2.53"], HostConfig__DnsSearch=["intra.example.com"],
            HostConfig__LogConfig={"Type": "json-file",
                                   "Config": {"max-size": "10m"}})
        inspect["Config"]["User"] = "70"
        inspect["Config"]["Cmd"] = ["postgres", "-c", "max_connections=300"]
        inspect["Config"]["Labels"]["owner"] = "ops"
        inspect["Config"]["Labels"]["com.docker.compose.project"] = "x"
        doc, blockers = convert(inspect)
        svc = doc["services"]["postgres"]
        self.assertEqual(blockers, [])
        self.assertEqual(svc["volumes"], ["/opt/pg/live-db:/var/lib/postgresql/data",
                                          "/etc/ssl/pg:/certs:ro"])
        self.assertEqual(svc["shm_size"], 1073741824)
        self.assertEqual(svc["mem_limit"], 2147483648)
        self.assertEqual(svc["cpus"], 1.5)
        self.assertEqual(svc["restart"], "on-failure:3")
        self.assertEqual(svc["ports"], ["127.0.0.1:5433:5432/tcp"])
        self.assertEqual(svc["extra_hosts"], ["registry:192.0.2.5"])
        self.assertEqual(svc["dns"], ["192.0.2.53"])
        self.assertEqual(svc["dns_search"], ["intra.example.com"])
        self.assertEqual(svc["logging"], {"driver": "json-file",
                                          "options": {"max-size": "10m"}})
        self.assertEqual(svc["user"], "70")
        self.assertEqual(svc["command"], ["postgres", "-c", "max_connections=300"])
        self.assertEqual(svc["labels"], {"owner": "ops"})

    def test_restart_policy_no_is_a_string(self):
        doc, _ = convert(legacy(HostConfig__RestartPolicy={"Name": "", "MaximumRetryCount": 0}))
        self.assertEqual(doc["services"]["postgres"]["restart"], "no")

    def test_named_volume_becomes_external(self):
        inspect = legacy(Mounts=[{"Type": "volume", "Name": "live-db-data",
                                  "Source": "/var/lib/docker/volumes/live-db-data/_data",
                                  "Destination": "/var/lib/postgresql/data", "RW": True}])
        doc, blockers = convert(inspect)
        self.assertEqual(blockers, [])
        self.assertEqual(doc["services"]["postgres"]["volumes"],
                         ["live-db-data:/var/lib/postgresql/data"])
        self.assertEqual(doc["volumes"], {"live-db-data": {"external": True}})
        self.assertNotIn("x-pgup-warnings", doc)

    def test_anonymous_data_volume_is_kept_by_name_with_warning(self):
        name = "ab12" * 16
        inspect = legacy(Mounts=[{"Type": "volume", "Name": name,
                                  "Source": "/var/lib/docker/volumes/%s/_data" % name,
                                  "Destination": "/var/lib/postgresql/data", "RW": True}])
        doc, blockers = convert(inspect)
        self.assertEqual(blockers, [])
        self.assertEqual(doc["services"]["postgres"]["volumes"],
                         [name + ":/var/lib/postgresql/data"])
        self.assertEqual(doc["volumes"], {name: {"external": True}})
        self.assertEqual(len(doc["x-pgup-warnings"]), 1)
        self.assertIn("anonymous", doc["x-pgup-warnings"][0])

    def test_unknown_settings_block_instead_of_being_dropped(self):
        doc, blockers = convert(legacy(HostConfig__Links=["other:o"],
                                       HostConfig__CapAdd=["SYS_NICE"]))
        self.assertIsNone(doc)
        self.assertEqual(len(blockers), 2)
        self.assertTrue(any("Links" in b for b in blockers))
        self.assertTrue(any("CapAdd" in b for b in blockers))

    def test_unset_values_do_not_block(self):
        doc, blockers = convert(legacy(HostConfig__Privileged=False, HostConfig__Tmpfs=None,
                                       HostConfig__SecurityOpt=[], HostConfig__PidMode="",
                                       HostConfig__IpcMode="shareable"))
        self.assertEqual(blockers, [])
        self.assertIsNotNone(doc)

    def test_other_blockers(self):
        for change in ({"HostConfig__Privileged": True}, {"HostConfig__PidMode": "host"},
                       {"HostConfig__NetworkMode": "host"},
                       {"HostConfig__NetworkMode": "container:abc"},
                       {"HostConfig__Ulimits": [{"Name": "nofile"}]},
                       {"HostConfig__Devices": [{"PathOnHost": "/dev/x"}]},
                       {"HostConfig__VolumesFrom": ["x"]}, {"HostConfig__SecurityOpt": ["a"]},
                       {"HostConfig__Tmpfs": {"/tmp": ""}}, {"HostConfig__CapDrop": ["ALL"]},
                       {"HostConfig__IpcMode": "host"}, {"HostConfig__UTSMode": "host"}):
            with self.subTest(change=change):
                doc, blockers = convert(legacy(**change))
                self.assertIsNone(doc)
                self.assertEqual(len(blockers), 1)

    def test_other_mount_type_and_missing_data_mount_block(self):
        inspect = legacy()
        inspect["Mounts"].append({"Type": "tmpfs", "Destination": "/scratch", "RW": True})
        doc, blockers = convert(inspect)
        self.assertIsNone(doc)
        self.assertTrue(any("tmpfs" in b for b in blockers))
        doc, blockers = convert(legacy(Mounts=[]))
        self.assertIsNone(doc)
        self.assertTrue(any("no data mount found" in b for b in blockers))

    def test_default_bridge_blocks(self):
        inspect = legacy(NetworkSettings__Networks={"bridge": {"Aliases": None}},
                         HostConfig__NetworkMode="default")
        doc, blockers = convert(inspect)
        self.assertIsNone(doc)
        self.assertTrue(any("bridge" in b for b in blockers))

    def test_network_alias_and_address_are_kept(self):
        inspect = legacy()
        inspect["NetworkSettings"]["Networks"]["live-db-net"]["IPAMConfig"] = {
            "IPv4Address": "192.0.2.10"}
        doc, _ = convert(inspect)
        self.assertEqual(doc["services"]["postgres"]["networks"]["live-db-net"],
                         {"aliases": ["db"], "ipv4_address": "192.0.2.10"})

    def test_missing_healthcheck_gets_ours(self):
        doc, _ = convert()
        hc = doc["services"]["postgres"]["healthcheck"]
        self.assertEqual(hc["test"], ["CMD-SHELL", "pg_isready -U ownerp -d postgres"])
        self.assertEqual((hc["interval"], hc["timeout"], hc["retries"], hc["start_period"]),
                         ("10s", "5s", 5, "30s"))

    def test_existing_healthcheck_is_kept(self):
        inspect = legacy()
        inspect["Config"]["Healthcheck"] = {"Test": ["CMD-SHELL", "true"],
                                            "Interval": 30000000000, "Retries": 3}
        doc, _ = convert(inspect)
        hc = doc["services"]["postgres"]["healthcheck"]
        self.assertEqual(hc["test"], ["CMD-SHELL", "true"])
        self.assertEqual(hc["interval"], "30s")
        self.assertEqual(hc["retries"], 3)

    def test_vector_context_adds_build(self):
        doc, _ = convert(vector_context="/opt/pg/live-db-deploy/pgvector")
        svc = doc["services"]["postgres"]
        self.assertEqual(svc["build"], {"context": "/opt/pg/live-db-deploy/pgvector",
                                        "args": {"PG_VERSION": "16.16-bookworm"}})

    def test_deploy_dir(self):
        bind = {"Type": "bind", "Source": "/opt/pg/live-db"}
        vol = {"Type": "volume", "Name": "v", "Source": "/var/lib/docker/volumes/v/_data"}
        self.assertEqual(pg.deploy_dir_for("live-db", bind, "/root"), "/opt/pg/live-db-deploy")
        self.assertEqual(pg.deploy_dir_for("live-db", vol, "/root"), "/root/pg-deploy/live-db")


REAL_HOSTCONFIG = {
    "Binds": ["/opt/pg/live-db:/var/lib/postgresql/data"], "ContainerIDFile": "",
    "LogConfig": {"Type": "json-file", "Config": {}}, "NetworkMode": "live-db-net",
    "PortBindings": {}, "RestartPolicy": {"Name": "always", "MaximumRetryCount": 0},
    "AutoRemove": False, "VolumeDriver": "", "VolumesFrom": None, "ConsoleSize": [0, 0],
    "CapAdd": None, "CapDrop": None, "CgroupnsMode": "private", "Dns": [], "DnsOptions": [],
    "DnsSearch": [], "ExtraHosts": None, "GroupAdd": None, "IpcMode": "private",
    "Cgroup": "", "Links": None, "OomScoreAdj": 0, "PidMode": "", "Privileged": False,
    "PublishAllPorts": False, "ReadonlyRootfs": False, "SecurityOpt": None,
    "UTSMode": "", "UsernsMode": "", "ShmSize": 67108864, "Runtime": "runc",
    "Isolation": "", "CpuShares": 0, "Memory": 0, "NanoCpus": 0, "CgroupParent": "",
    "BlkioWeight": 0, "BlkioWeightDevice": [], "BlkioDeviceReadBps": [],
    "BlkioDeviceWriteBps": [], "BlkioDeviceReadIOps": [], "BlkioDeviceWriteIOps": [],
    "CpuPeriod": 0, "CpuQuota": 0, "CpuRealtimePeriod": 0, "CpuRealtimeRuntime": 0,
    "CpusetCpus": "", "CpusetMems": "", "Devices": [], "DeviceCgroupRules": None,
    "DeviceRequests": None, "KernelMemory": 0, "KernelMemoryTCP": 0, "MemoryReservation": 0,
    "MemorySwap": 0, "MemorySwappiness": None, "OomKillDisable": False, "PidsLimit": None,
    "Ulimits": [], "CpuCount": 0, "CpuPercent": 0, "IOMaximumIOps": 0,
    "IOMaximumBandwidth": 0, "MaskedPaths": ["/proc/kcore", "/proc/keys"],
    "ReadonlyPaths": ["/proc/bus"], "Init": None, "Tmpfs": None, "Sysctls": None,
    "StorageOpt": None, "Annotations": None,
}


class HostConfigFailClosedTest(unittest.TestCase):
    def test_default_hostconfig_of_a_plain_container_has_no_blockers(self):
        doc, blockers = convert(legacy(HostConfig=json.loads(json.dumps(REAL_HOSTCONFIG))))
        self.assertEqual(blockers, [])
        self.assertIsNotNone(doc)

    def test_unknown_hostconfig_key_blocks(self):
        hostconfig = dict(REAL_HOSTCONFIG, FutureSetting="yes", Annotations={"a": "b"},
                          PidsLimit=100)
        doc, blockers = convert(legacy(HostConfig=hostconfig))
        self.assertIsNone(doc)
        self.assertEqual(len(blockers), 3)
        for key in ("FutureSetting", "Annotations", "PidsLimit"):
            self.assertEqual(len([b for b in blockers if b.startswith(key + " ")]), 1)
        # an unknown key with an empty value is no setting
        doc, blockers = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, FutureSetting=None)))
        self.assertEqual(blockers, [])

    def test_memoryswap_default_double_of_memory_is_not_a_blocker(self):
        gib = 1073741824
        doc, blockers = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, Memory=gib,
                                                       MemorySwap=2 * gib)))
        self.assertEqual(blockers, [])
        self.assertEqual(doc["services"]["postgres"]["mem_limit"], gib)
        self.assertNotIn("memswap_limit", doc["services"]["postgres"])
        doc, blockers = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, Memory=gib,
                                                       MemorySwap=3 * gib)))
        self.assertEqual(blockers, [])
        self.assertEqual(doc["services"]["postgres"]["memswap_limit"], 3 * gib)

    def test_unlimited_swap_with_memory_limit_is_carried(self):
        gib = 1073741824
        doc, _ = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, Memory=gib, MemorySwap=-1)))
        self.assertEqual(doc["services"]["postgres"]["memswap_limit"], -1)
        doc, _ = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, Memory=0, MemorySwap=-1)))
        self.assertNotIn("memswap_limit", doc["services"]["postgres"])

    def test_explicit_swappiness_zero_is_carried(self):
        for value, expected in ((0, 0), (60, 60)):
            doc, blockers = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG,
                                                           MemorySwappiness=value)))
            self.assertEqual(blockers, [])
            self.assertEqual(doc["services"]["postgres"]["mem_swappiness"], expected)
        for value in (None, -1):
            doc, _ = convert(legacy(HostConfig=dict(REAL_HOSTCONFIG, MemorySwappiness=value)))
            self.assertNotIn("mem_swappiness", doc["services"]["postgres"])

    def test_init_sysctls_groupadd_readonly_are_carried(self):
        doc, blockers = convert(legacy(HostConfig=dict(
            REAL_HOSTCONFIG, Init=True, Sysctls={"net.core.somaxconn": "1024"},
            GroupAdd=["staff"], ReadonlyRootfs=True, CpuShares=512, CpusetCpus="0-1")))
        svc = doc["services"]["postgres"]
        self.assertEqual(blockers, [])
        self.assertIs(svc["init"], True)
        self.assertEqual(svc["sysctls"], {"net.core.somaxconn": "1024"})
        self.assertEqual(svc["group_add"], ["staff"])
        self.assertIs(svc["read_only"], True)
        self.assertEqual(svc["cpu_shares"], 512)
        self.assertEqual(svc["cpuset"], "0-1")

    def test_stop_signal_only_when_different_from_image(self):
        image = json.loads(json.dumps(IMAGE))
        image["Config"]["StopSignal"] = "SIGINT"
        image["Config"]["WorkingDir"] = ""
        same = legacy()
        same["Config"]["StopSignal"] = "SIGINT"
        doc, _ = pg.compose_from_inspect(same, image, "postgres:16.16-bookworm", "ownerp")
        self.assertNotIn("stop_signal", doc["services"]["postgres"])
        other = legacy()
        other["Config"].update({"StopSignal": "SIGTERM", "StopTimeout": 120,
                                "WorkingDir": "/srv"})
        doc, _ = pg.compose_from_inspect(other, image, "postgres:16.16-bookworm", "ownerp")
        svc = doc["services"]["postgres"]
        self.assertEqual(svc["stop_signal"], "SIGTERM")
        self.assertEqual(svc["stop_grace_period"], "120s")
        self.assertEqual(svc["working_dir"], "/srv")

    def test_selinux_mount_mode_is_kept(self):
        inspect = legacy(Mounts=[{"Type": "bind", "Source": "/opt/pg/live-db",
                                  "Destination": "/var/lib/postgresql/data", "RW": True,
                                  "Mode": "z", "Propagation": "rprivate"}])
        doc, blockers = convert(inspect)
        self.assertEqual(blockers, [])
        self.assertEqual(doc["services"]["postgres"]["volumes"],
                         ["/opt/pg/live-db:/var/lib/postgresql/data:z"])
        inspect["Mounts"][0].update({"Mode": "ro,z", "RW": False})
        doc, _ = convert(inspect)
        self.assertEqual(doc["services"]["postgres"]["volumes"],
                         ["/opt/pg/live-db:/var/lib/postgresql/data:ro,z"])
        inspect["Mounts"][0].update({"Mode": "rw", "RW": True, "Propagation": "shared"})
        doc, blockers = convert(inspect)
        self.assertIsNone(doc)
        self.assertEqual(len(blockers), 1)

    def test_ipv6_host_ip_is_bracketed(self):
        doc, _ = convert(legacy(HostConfig__PortBindings={
            "5432/tcp": [{"HostIp": "::1", "HostPort": "5433"}]}))
        self.assertEqual(doc["services"]["postgres"]["ports"], ["[::1]:5433:5432/tcp"])


class ComposeFileTest(unittest.TestCase):
    def test_written_file_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "docker-compose.yml")
            pg.write_private(path, "secret: 1\n")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "secret: 1\n")

    def test_write_over_a_world_readable_file_ends_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "docker-compose.yml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("old\n")
            os.chmod(path, 0o644)
            pg.write_private(path, "new\n")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "new\n")

    def test_mask_hides_passwords(self):
        doc, _ = convert()
        text = pg.render_compose(doc, "live-db")
        self.assertIn("pa$$word", text)
        masked = pg.mask_compose(text)
        self.assertNotIn("pa$$word", masked)
        self.assertEqual(yaml.safe_load(masked)["services"]["postgres"]["environment"]
                         ["POSTGRES_PASSWORD"], "***")
        self.assertIn("POSTGRES_USER: ownerp", masked)

    def test_rendered_text_parses_back_to_the_document(self):
        doc, _ = convert(legacy(HostConfig__RestartPolicy={"Name": "", "MaximumRetryCount": 0}))
        text = pg.render_compose(doc, "live-db")
        self.assertEqual(yaml.safe_load(text), doc)
        self.assertTrue(text.startswith("#"))
        self.assertIn("live-db", text.splitlines()[0])
        self.assertIn("docker compose -f docker-compose.yml up -d", text)
        self.assertEqual(yaml.safe_load(text)["services"]["postgres"]["restart"], "no")


class PatchComposeTest(unittest.TestCase):
    def test_patch_touches_one_service_only(self):
        out = pg.patch_compose_image(TWO_SERVICES, "postgres", "postgres:16.16-bookworm", None)
        changed = [b for a, b in zip(TWO_SERVICES.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(changed, ['    image: "postgres:16.16-bookworm"'])
        self.assertEqual(len(out.splitlines()), len(TWO_SERVICES.splitlines()))

    def test_patch_keeps_quote_style(self):
        text = TWO_SERVICES.replace("image: postgres:16.15-bookworm",
                                    "image: 'postgres:16.15-bookworm'")
        out = pg.patch_compose_image(text, "postgres", "postgres:16.16-bookworm", None)
        self.assertIn("    image: 'postgres:16.16-bookworm'\n", out)

    def test_patch_also_sets_the_pgvector_build_argument(self):
        out = pg.patch_compose_image(TWO_SERVICES, "postgres", "postgres:16.16-bookworm",
                                     "16.16-bookworm")
        changed = [b for a, b in zip(TWO_SERVICES.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(changed, ['    image: "postgres:16.16-bookworm"',
                                   '        PG_VERSION: "16.16-bookworm"'])

    def test_patch_keeps_line_endings(self):
        text = TWO_SERVICES.replace("\n", "\r\n").rstrip("\r\n")
        out = pg.patch_compose_image(text, "postgres", "postgres:16.16-bookworm", None)
        self.assertNotIn("\r\n\r\n", out)
        self.assertEqual(out.count("\r\n"), text.count("\r\n"))
        self.assertFalse(out.endswith("\n"))

    def test_patch_refuses_a_file_it_cannot_follow(self):
        with self.assertRaises(ValueError):
            pg.patch_compose_image(TWO_SERVICES, "missing", "postgres:16.16-bookworm", None)
        with self.assertRaises(ValueError):
            pg.patch_compose_image(TWO_SERVICES, "adminer", "adminer:5", "5")
        with self.assertRaises(ValueError):
            pg.patch_compose_image("services:\n  postgres:\n    restart: always\n",
                                   "postgres", "y", None)


class VectorDockerfileTest(unittest.TestCase):
    def test_matches_the_deploy_script(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts",
                               "pg-local-deploy.sh"), encoding="utf-8") as handle:
            text = handle.read()
        start = text.index("ARG PG_VERSION\n")
        end = text.index("EOF_PGVECTOR", start)
        self.assertEqual(pg.VECTOR_DOCKERFILE, text[start:end])


# ── Phase 1: plan, pull, guards, backup ──────────────────────────────────────

GIB = 1024 ** 3
UPDATE_CHOICE = pg.Choice("postgres:16.16-bookworm", (16, 16), "16.8 -> 16.16")
NEW_BASE = DEBIAN_12 + "ldd (Debian GLIBC 2.36-9+deb12u10) 2.36\n"
LIST_DBS = ("docker", "exec", "live-db", "psql", "-U", "ownerp", "-d", "postgres", "-Atqc",
            "SELECT datname FROM pg_database WHERE datistemplate = false")


def size_query(db):
    return ("docker", "exec", "live-db", "psql", "-U", "ownerp", "-d", "postgres", "-Atqc",
            "SELECT pg_database_size('%s')" % db)


class Phase1Case(unittest.TestCase):
    """A tempdir with a data directory (PG_VERSION inside) and a legacy target on it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pgup-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = os.path.join(self.tmp, "live-db")
        os.makedirs(self.data)
        with open(os.path.join(self.data, "PG_VERSION"), "w") as handle:
            handle.write("16\n")
        self.deploy = os.path.join(self.tmp, "live-db-deploy")
        self.opts = pg.Options(home=self.tmp, update_config=os.path.join(self.tmp, "nope.yaml"),
                               backup_config=os.path.join(self.tmp, "nope2.yaml"))

    def inspect(self, **changes):
        changes.setdefault("State", {"Running": True})
        changes.setdefault("Mounts", [{"Type": "bind", "Source": self.data,
                                       "Destination": "/var/lib/postgresql/data", "RW": True}])
        return legacy(**changes)

    def legacy_target(self, **kw):
        values = dict(kind="legacy", base=BOOKWORM, inspect=self.inspect(), pgdata=self.data,
                      db_user="ownerp", odoo=[odoo_info()])
        values.update(kw)
        return target(**values)

    def answers(self, extra=None):
        base = {
            ("docker", "compose", "version"): (0, "Docker Compose version v2.29"),
            ("docker", "image", "inspect", "postgres:16.8"): (0, json.dumps([IMAGE])),
            ("docker", "pull"): (0, ""),
            ("docker", "run", "--rm", "--entrypoint", "sh"): (0, NEW_BASE),
            LIST_DBS: (0, "postgres\nlive_db\n"),
            size_query("live_db"): (0, "1000\n"),
        }
        base.update(extra or {})
        return base

    def runner(self, extra=None):
        return FakeRunner(self.answers(extra))

    def free(self, nbytes):
        return lambda path: type("Usage", (), {"free": nbytes, "total": 10 * nbytes,
                                               "used": 0})()

    def prepare(self, tgt=None, choice=UPDATE_CHOICE, run=None, free=100 * GIB, opts=None):
        run = run or self.runner()
        plan = pg.prepare(tgt or self.legacy_target(), choice, opts or self.opts, run,
                          disk_usage=self.free(free))
        return plan, run


class PrepareTest(Phase1Case):
    def test_unknown_pgdata_blocks_before_anything_stops(self):
        run = self.runner()
        plan = pg.prepare(self.legacy_target(pgdata=None), UPDATE_CHOICE, self.opts, run,
                          disk_usage=self.free(GIB))
        self.assertIn("data directory not found", plan.problems[0])
        self.assertFalse(any(c[:2] == ["docker", "stop"] for c in run.calls))
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in run.calls))

    def test_missing_pg_version_file_is_a_problem(self):
        os.unlink(os.path.join(self.data, "PG_VERSION"))
        plan, _ = self.prepare()
        self.assertTrue(any("PG_VERSION" in p for p in plan.problems))

    def test_unreadable_data_directory_asks_for_root(self):
        original = os.path.isfile

        def denied(path):
            if str(path).endswith("PG_VERSION"):
                raise PermissionError(13, "denied")
            return original(path)

        os.path.isfile = denied
        try:
            plan, _ = self.prepare()
        finally:
            os.path.isfile = original
        self.assertTrue(any("needs root" in p for p in plan.problems))

    def test_blocked_choice_and_stopped_container_are_problems(self):
        plan, _ = self.prepare(choice=pg.Choice(None, None, "x",
                                                blocked="major upgrades are not supported"))
        self.assertIn("major upgrades are not supported", plan.problems)
        plan, _ = self.prepare(tgt=self.legacy_target(
            inspect=self.inspect(State={"Running": False})))
        self.assertTrue(any("not running" in p for p in plan.problems))

    def test_image_is_pulled_in_phase_one(self):
        plan, run = self.prepare()
        self.assertEqual(plan.problems, [])
        self.assertIn(["docker", "pull", "postgres:16.16-bookworm"], run.calls)
        self.assertEqual(plan.compose_file, os.path.join(self.deploy, "docker-compose.yml"))
        self.assertEqual(plan.parked_name, "live-db-pre-16.8")
        self.assertEqual(plan.databases, ["live_db"])
        self.assertIn("postgres:16.16-bookworm", plan.compose_text)
        # nothing was written to the host
        self.assertFalse(os.path.exists(self.deploy))

    def test_pull_failure_is_a_problem(self):
        plan, _ = self.prepare(run=self.runner({("docker", "pull"): (1, "denied")}))
        self.assertTrue(any("pull" in p for p in plan.problems))

    def test_libc_change_is_a_problem(self):
        newer = DEBIAN_12.replace("bookworm", "trixie") + "ldd (Debian GLIBC 2.41-1) 2.41\n"
        plan, _ = self.prepare(run=self.runner({
            ("docker", "run", "--rm", "--entrypoint", "sh"): (0, newer)}))
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("base system would change (glibc 2.36 -> glibc 2.41)", plan.problems[0])
        self.assertIn("16.x-bookworm", plan.problems[0])

    def test_libc_guard_also_covers_a_verbatim_to_tag(self):
        newer = "ldd (Debian GLIBC 2.41-1) 2.41\n"
        plan, _ = self.prepare(choice=pg.Choice("postgres:16.16", (16, 16), "requested"),
                               run=self.runner({("docker", "run", "--rm", "--entrypoint",
                                                 "sh"): (0, newer)}))
        self.assertTrue(any("base system would change" in p for p in plan.problems))

    def test_missing_compose_is_a_problem(self):
        run = self.runner({("docker", "compose", "version"): (1, "")})
        plan, run = self.prepare(run=run)
        self.assertIn("docker compose is not installed", plan.problems)
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in run.calls))

    def test_old_docker_compose_binary_is_found(self):
        run = self.runner({("docker", "compose", "version"): (1, ""),
                           ("docker-compose", "version"): (0, "1.29")})
        self.assertEqual(pg.compose_cmd(run), ["docker-compose"])
        self.assertEqual(pg.compose_cmd(self.runner()), ["docker", "compose"])
        self.assertIsNone(pg.compose_cmd(FakeRunner()))

    def test_existing_parked_container_is_a_problem(self):
        run = self.runner({("docker", "inspect", "live-db-pre-16.8"): (0, "[{}]")})
        plan, _ = self.prepare(run=run)
        self.assertIn("live-db-pre-16.8 exists from an earlier update; remove it or roll "
                      "back first", plan.problems)

    def test_conversion_blockers_become_problems(self):
        tgt = self.legacy_target(inspect=self.inspect(HostConfig__Privileged=True))
        plan, _ = self.prepare(tgt=tgt)
        self.assertTrue(any("Privileged" in p for p in plan.problems))
        self.assertIsNone(plan.compose_text)

    def test_current_legacy_container_gets_a_conversion_only_plan(self):
        plan, run = self.prepare(choice=CURRENT)
        self.assertEqual(plan.problems, [])
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in run.calls))
        self.assertFalse(any(c[:2] == ["docker", "run"] for c in run.calls))
        self.assertIn("image: postgres:16.8", plan.compose_text)
        self.assertIn("conversion to compose only, version stays 16.8", pg.render_plan(plan))

    def test_current_compose_container_has_nothing_to_do(self):
        compose = os.path.join(self.tmp, "docker-compose.yml")
        tgt = self.legacy_target(kind="compose", compose_file=compose, compose_service="postgres")
        plan, _ = self.prepare(tgt=tgt, choice=CURRENT)
        self.assertEqual(plan.problems, ["nothing to do"])

    def test_compose_managed_target_gets_a_patched_file(self):
        compose = os.path.join(self.tmp, "docker-compose.yml")
        with open(compose, "w") as handle:
            handle.write("services:\n  postgres:\n    image: postgres:16.8\n")
        tgt = self.legacy_target(kind="compose", compose_file=compose, compose_service="postgres")
        plan, _ = self.prepare(tgt=tgt)
        self.assertEqual(plan.problems, [])
        self.assertIn("postgres:16.16-bookworm", plan.compose_text)
        self.assertIsNone(plan.parked_name)
        self.assertEqual(plan.compose_file, compose)
        self.assertEqual(plan.deploy_dir, self.tmp)

    def test_unreadable_or_unpatchable_compose_file_is_a_problem(self):
        compose = os.path.join(self.tmp, "docker-compose.yml")
        tgt = self.legacy_target(kind="compose", compose_file=compose, compose_service="postgres")
        plan, _ = self.prepare(tgt=tgt)
        self.assertTrue(any("cannot read" in p for p in plan.problems))
        with open(compose, "w") as handle:
            handle.write("services:\n  other:\n    image: x\n")
        plan, _ = self.prepare(tgt=tgt)
        self.assertTrue(any("service postgres not found" in p for p in plan.problems))

    def test_only_running_odoo_is_listed_for_stop(self):
        tgt = self.legacy_target(odoo=[odoo_info(), odoo_info(name="old-odoo", running=False)])
        plan, _ = self.prepare(tgt=tgt)
        self.assertEqual(plan.stop_odoo, ["live-odoo"])

    def test_free_space_rule_for_own_dump(self):
        run = self.runner({size_query("live_db"): (0, "%d\n" % (10 * GIB))})
        plan, _ = self.prepare(run=run, free=5 * GIB)
        self.assertEqual(len(plan.problems), 1)
        self.assertIn("live_db", plan.problems[0])
        self.assertIn("10.0 GiB", plan.problems[0])
        self.assertIn("5.0 GiB", plan.problems[0])
        skipping = pg.Options(home=self.tmp, skip_backup=True,
                              update_config=self.opts.update_config,
                              backup_config=self.opts.backup_config)
        plan, _ = self.prepare(run=run, free=5 * GIB, opts=skipping)
        self.assertEqual(plan.problems, [])

    def test_free_space_rule_uses_the_sum_of_unlisted_databases(self):
        run = self.runner({LIST_DBS: (0, "postgres\nlive_db\nsecond\n"),
                           size_query("live_db"): (0, "%d\n" % (3 * GIB)),
                           size_query("second"): (0, "%d\n" % (3 * GIB))})
        plan, _ = self.prepare(run=run, free=5 * GIB)
        self.assertEqual(len(plan.problems), 1)
        for text in ("live_db", "second", "6.0 GiB", "5.0 GiB"):
            self.assertIn(text, plan.problems[0])
        plan, _ = self.prepare(run=run, free=7 * GIB)
        self.assertEqual(plan.problems, [])

    def test_listed_databases_need_no_space_check(self):
        cfg = os.path.join(self.tmp, "backup.yaml")
        with open(cfg, "w") as handle:
            yaml.safe_dump({"defaults": {"backup_path": "/opt/backups"},
                            "databases": [{"name": "live_db", "sql_container": "live-db"}]},
                           handle)
        opts = pg.Options(home=self.tmp, update_config=self.opts.update_config, backup_config=cfg)
        run = self.runner({size_query("live_db"): (0, "%d\n" % (10 * GIB))})
        plan, _ = self.prepare(run=run, free=GIB, opts=opts)
        self.assertEqual(plan.problems, [])
        self.assertEqual((plan.listed, plan.unlisted), (["live_db"], []))

    def test_pgvector_dockerfile_is_written_when_missing(self):
        tgt = self.legacy_target(vector=True, image="postgres-pgvector:16.8-bookworm")
        choice = pg.Choice("postgres-pgvector:16.16-bookworm", (16, 16), "x")
        run = self.runner({
            ("docker", "image", "inspect", "postgres-pgvector:16.8-bookworm"):
                (0, json.dumps([IMAGE])),
            ("docker", "build"): (0, "")})
        plan, run = self.prepare(tgt=tgt, choice=choice, run=run)
        self.assertEqual(plan.problems, [])
        dockerfile = os.path.join(self.deploy, "pgvector", "Dockerfile")
        with open(dockerfile) as handle:
            self.assertEqual(handle.read(), pg.VECTOR_DOCKERFILE)
        build = next(c for c in run.calls if c[:2] == ["docker", "build"])
        self.assertEqual(build, ["docker", "build", "--build-arg", "PG_VERSION=16.16-bookworm",
                                 "-t", "postgres-pgvector:16.16-bookworm",
                                 os.path.join(self.deploy, "pgvector")])
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in run.calls))
        # an existing Dockerfile is left alone
        with open(dockerfile, "w") as handle:
            handle.write("custom\n")
        self.prepare(tgt=tgt, choice=choice, run=run)
        with open(dockerfile) as handle:
            self.assertEqual(handle.read(), "custom\n")

    def test_failed_build_is_a_problem(self):
        tgt = self.legacy_target(vector=True, image="postgres-pgvector:16.8-bookworm")
        run = self.runner({
            ("docker", "image", "inspect", "postgres-pgvector:16.8-bookworm"):
                (0, json.dumps([IMAGE])),
            ("docker", "build"): (1, "boom")})
        plan, _ = self.prepare(tgt=tgt, run=run, choice=pg.Choice(
            "postgres-pgvector:16.16-bookworm", (16, 16), "x"))
        self.assertTrue(any("build" in p for p in plan.problems))


class RenderPlanTest(Phase1Case):
    def test_dry_run_plan_masks_the_password(self):
        plan, _ = self.prepare()
        self.assertIn("pa$$word", plan.compose_text)
        text = pg.render_plan(plan, dry_run=True)
        self.assertNotIn("pa$$word", text)
        self.assertNotIn("pa$word", text)
        self.assertIn("POSTGRES_PASSWORD", text)
        self.assertNotIn("pa$$word", pg.render_plan(plan))

    def test_plan_lists_the_steps_in_order(self):
        tgt = self.legacy_target(others=["adminer"])
        plan, _ = self.prepare(tgt=tgt)
        text = pg.render_plan(plan)
        order = ["live-db", "glibc 2.36", "live-odoo", "adminer", "live_db",
                 plan.compose_file, "pgup --rollback live-db"]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_problems_come_first_and_nothing_promises_the_update(self):
        plan, _ = self.prepare(tgt=self.legacy_target(pgdata=None))
        text = pg.render_plan(plan)
        self.assertTrue(text.startswith("Cannot update live-db:"))
        self.assertNotIn("pgup --rollback", text)

    def test_plan_and_json_carry_the_release_notes(self):
        choice = pg.Choice("postgres:16.10-bookworm", (16, 10), "x")
        plan, _ = self.prepare(choice=choice)
        text = pg.render_plan(plan)
        self.assertIn("Release notes to read first (a patch release can require a manual "
                      "step afterwards):", text)
        self.assertIn("https://www.postgresql.org/docs/release/16.10/", text)
        self.assertLess(text.index("Release notes to read first"),
                        text.index("pgup --rollback"))
        rows = [(plan.target, choice, [])]
        self.assertEqual(pg.overview_json(rows)["containers"][0]["update"]["release_notes"],
                         ["https://www.postgresql.org/docs/release/16.10/",
                          "https://www.postgresql.org/docs/release/16.9/"])
        none = pg.overview_json([(plan.target, CURRENT, [])])
        self.assertEqual(none["containers"][0]["update"]["release_notes"], [])

    def test_release_note_links(self):
        self.assertEqual(pg.release_note_links((16, 8), (16, 10)),
                         ["https://www.postgresql.org/docs/release/16.10/",
                          "https://www.postgresql.org/docs/release/16.9/"])
        self.assertEqual(pg.release_note_links((16, 10), (16, 10)), [])
        self.assertEqual(pg.release_note_links((16, 10), (16, 8)), [])


class BackupTest(Phase1Case):
    def make_plan(self, listed, unlisted, **kw):
        values = dict(target=self.legacy_target(), choice=UPDATE_CHOICE, deploy_dir=self.deploy,
                      compose_file=os.path.join(self.deploy, "docker-compose.yml"),
                      compose_text="", databases=listed + unlisted, listed=listed,
                      unlisted=unlisted, stop_odoo=[], sizing=NO_SIZING, parked_name=None,
                      problems=[])
        values.update(kw)
        return pg.UpdatePlan(**values)

    def backup(self, plan, run=None, stream=None, dump=None, opts=None):
        run = run or FakeRunner({("docker", "exec", "live-db", "pg_dumpall"):
                                 (0, "CREATE ROLE ownerp;\n")})
        stream = stream or FakeRunner({(sys.executable,): (0, "")})
        dumped = []

        def fake_dump(argv, path):
            dumped.append((list(argv), path))
            with open(path, "wb") as handle:
                handle.write(b"PGDMP")
            return 0

        original = pg._dump_to_file
        pg._dump_to_file = dump or fake_dump
        self.addCleanup(setattr, pg, "_dump_to_file", original)
        lines = []
        result = pg.backup(plan, opts or self.opts, run, stream, lines.append)
        return result, run, stream, dumped, lines

    def test_backup_uses_dobk_for_listed_and_dump_for_unlisted(self):
        cfg = os.path.join(self.tmp, "backup.yaml")
        with open(cfg, "w") as handle:
            yaml.safe_dump({"defaults": {"backup_path": "/opt/backups"}}, handle)
        opts = pg.Options(home=self.tmp, update_config=self.opts.update_config, backup_config=cfg)
        plan = self.make_plan(["a"], ["b"])
        (ok, locations), run, stream, dumped, _ = self.backup(plan, opts=opts)
        self.assertTrue(ok)
        self.assertEqual(stream.calls, [[sys.executable,
                                         os.path.join(self.tmp, "container2backup.py"),
                                         "--sql-only", "--only-db", "a"]])
        self.assertIn("/opt/backups", locations)
        self.assertEqual(dumped[0][0], ["docker", "exec", "live-db", "pg_dump", "-U", "ownerp",
                                        "-Fc", "--dbname=b"])
        dump = dumped[0][1]
        self.assertTrue(dump.startswith(os.path.join(self.deploy, "pre-update") + os.sep))
        self.assertTrue(dump.endswith(os.sep + "b.dump"))
        self.assertTrue(os.path.isfile(dump))
        self.assertEqual(os.stat(dump).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(dump)).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.deploy, "pre-update")).st_mode & 0o777, 0o700)
        self.assertIn(dump, locations)

    def test_globals_are_always_dumped_with_mode_0600(self):
        plan = self.make_plan([], [])
        (ok, locations), run, stream, dumped, _ = self.backup(plan)
        self.assertTrue(ok)
        self.assertEqual(stream.calls, [])
        self.assertEqual(dumped, [])
        self.assertIn(["docker", "exec", "live-db", "pg_dumpall", "-U", "ownerp",
                       "--globals-only"], run.calls)
        files = [f for f in os.listdir(self.deploy) if f.startswith("globals-")
                 and f.endswith(".sql")]
        self.assertEqual(len(files), 1)
        path = os.path.join(self.deploy, files[0])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with open(path) as handle:
            self.assertEqual(handle.read(), "CREATE ROLE ownerp;\n")
        self.assertIn(path, locations)

    def test_dump_to_file_writes_binary_stdout(self):
        path = os.path.join(self.tmp, "x.dump")
        code = pg._dump_to_file([sys.executable, "-c",
                                 "import sys; sys.stdout.buffer.write(b'PG\\xff\\x00')"], path)
        self.assertEqual(code, 0)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"PG\xff\x00")
        self.assertEqual(pg._dump_to_file([sys.executable, "-c", "raise SystemExit(3)"], path), 3)

    def test_failed_dobk_fails_the_backup(self):
        plan = self.make_plan(["a"], ["b"])
        (ok, _), run, stream, dumped, lines = self.backup(
            plan, stream=FakeRunner({(sys.executable,): (2, "")}))
        self.assertFalse(ok)
        self.assertEqual(dumped, [])
        self.assertFalse(any("pg_dumpall" in c for c in run.calls))

    def test_failed_dump_fails_and_keeps_what_was_written(self):
        written = []

        def failing(argv, path):
            with open(path, "wb") as handle:
                handle.write(b"half")
            written.append(path)
            return 1

        plan = self.make_plan([], ["b"])
        (ok, _), _, _, _, lines = self.backup(plan, dump=failing)
        self.assertFalse(ok)
        self.assertEqual(len(os.listdir(os.path.dirname(written[0]))), 1)   # nothing deleted
        self.assertTrue(lines)

    def test_failed_globals_dump_fails_the_backup(self):
        plan = self.make_plan([], [])
        (ok, _), *_ = self.backup(plan, run=FakeRunner())
        self.assertFalse(ok)

    def test_skip_backup_warns_and_does_nothing(self):
        opts = pg.Options(home=self.tmp, skip_backup=True)
        plan = self.make_plan(["a"], ["b"])
        (ok, locations), run, stream, dumped, lines = self.backup(plan, opts=opts)
        self.assertEqual((ok, locations), (True, []))
        self.assertEqual((run.calls, stream.calls, dumped), ([], [], []))
        self.assertEqual(len(lines), 1)
        self.assertIn("WARNING", lines[0])


# ── Phase 2: switch, verify, undo, rollback ──────────────────────────────────

class Host(FakeRunner):
    """A small stateful Docker host: containers, one compose project, the server answers.

    `fail` maps a command prefix to a fixed answer and wins over the simulation;
    `hooks` are called with every argv before it is answered.
    """

    def __init__(self, old="postgres:16.8", new="postgres:16.16-bookworm", compose_owned=False):
        super().__init__({})
        self.new = new
        self.versions = {old: "16.8", new: "16.16"}
        self.containers = {
            "live-db": {"image": old, "running": True, "restart": "always",
                        "compose": compose_owned},
            "live-odoo": {"image": "eq/odoo:18", "running": True, "restart": "always",
                          "compose": False},
            "old-odoo": {"image": "eq/odoo:18", "running": False, "restart": "no",
                         "compose": False},
        }
        self.databases = "postgres\nlive_db\n"
        self.databases_switched = None      # other answer once the compose project is up
        self.collation_switched = ""        # collation query answer once it is up
        self.not_ready = set()              # images whose server never answers pg_isready
        self.switched = False
        self.fail = {}
        self.hooks = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        for hook in self.hooks:
            hook(list(argv))
        for prefix, answer in self.fail.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return answer
        return self.simulate(list(argv))

    def inspect_json(self, name):
        item = self.containers[name]
        return json.dumps([{"Name": "/" + name, "State": {"Running": item["running"]},
                            "Config": {"Image": item["image"]},
                            "HostConfig": {"RestartPolicy": {"Name": item["restart"],
                                                             "MaximumRetryCount": 0}}}])

    def simulate(self, argv):
        if argv[:3] == ["docker", "compose", "version"]:
            return 0, "v2"
        if argv[:3] == ["docker", "compose", "-f"] and argv[4:] == ["up", "-d"]:
            with open(argv[3]) as handle:
                image = yaml.safe_load(handle)["services"]["postgres"]["image"]
            existing = self.containers.get("live-db")
            if existing and not existing["compose"]:
                return 1, "Conflict. The container name /live-db is already in use"
            self.containers["live-db"] = {"image": image, "running": True,
                                          "restart": "always", "compose": True}
            self.switched = True
            return 0, ""
        if argv[:3] == ["docker", "compose", "-f"] and argv[4:] == ["down"]:
            if self.containers.get("live-db", {}).get("compose"):
                del self.containers["live-db"]
            return 0, ""
        if argv[:2] == ["docker", "inspect"] and argv[2:4] == ["--type", "container"]:
            if argv[4] in self.containers:
                return 0, self.inspect_json(argv[4])
            return 1, "Error: No such container: " + argv[4]
        if argv[:2] in (["docker", "stop"], ["docker", "start"]):
            if argv[2] not in self.containers:
                return 1, "Error: No such container: " + argv[2]
            self.containers[argv[2]]["running"] = argv[1] == "start"
            return 0, ""
        if argv[:2] == ["docker", "rename"]:
            if argv[2] not in self.containers or argv[3] in self.containers:
                return 1, "rename failed"
            self.containers[argv[3]] = self.containers.pop(argv[2])
            self.containers[argv[3]]["compose"] = False
            return 0, ""
        if argv[:2] == ["docker", "update"] and argv[2].startswith("--restart="):
            self.containers[argv[3]]["restart"] = argv[2].partition("=")[2]
            return 0, ""
        if argv[:2] == ["docker", "exec"]:
            item = self.containers.get(argv[2])
            if not item or not item["running"]:
                return 1, "is not running"
            if argv[3] == "pg_isready":
                return (1, "no response") if item["image"] in self.not_ready else (0, "")
            query = argv[-1]
            if query == "SHOW server_version":
                return 0, self.versions[item["image"]] + "\n"
            if "datistemplate" in query:
                if self.switched and self.databases_switched is not None:
                    return 0, self.databases_switched
                return 0, self.databases
            if "datcollversion" in query:
                return 0, self.collation_switched if self.switched else ""
        return 1, ""

    def changes(self):
        """The calls that change something, in order (backup stub included)."""
        found = []
        for call in self.calls:
            if call[0] == "<backup>" or call[:2] in (["docker", "stop"], ["docker", "start"],
                                                    ["docker", "rename"], ["docker", "update"]):
                found.append(call)
            elif call[:3] == ["docker", "compose", "-f"] and call[4:] in (["up", "-d"], ["down"]):
                found.append(call)
        return found


class UpdateCase(Phase1Case):
    def setUp(self):
        super().setUp()
        self.host = Host()
        self.lines = []
        self.backup_result = (True, ["/opt/backups"])
        self.patches = []
        self.addCleanup(self.stop_patches)
        self.patch(pg, "backup", self.fake_backup)

    def stop_patches(self):
        for patcher in reversed(self.patches):     # the last patch undone first
            patcher.stop()

    def patch(self, obj, name, value):
        patcher = mock.patch.object(obj, name, value)
        patcher.start()
        self.patches.append(patcher)

    def fake_backup(self, plan, opts, run, stream, out):
        run(["<backup>"])
        return self.backup_result

    def plan(self, **kw):
        plan, _ = self.prepare(**kw)
        self.assertEqual(plan.problems, [])
        return plan

    def update(self, plan, host=None, opts=None):
        host = host or self.host
        return pg.update_one(plan, opts or self.opts, host, FakeRunner(), self.lines.append,
                             sleep=lambda seconds: None)

    def text(self):
        return "\n".join(self.lines)

    def state_file(self):
        return pg.state_path(self.tmp, "live-db")

    def started(self, name):
        return ["docker", "start", name] in self.host.calls

    def options(self, **kw):
        return pg.Options(home=self.tmp, update_config=self.opts.update_config,
                          backup_config=self.opts.backup_config, **kw)

    def assert_old_server_back(self):
        live = self.host.containers["live-db"]
        self.assertEqual((live["image"], live["running"], live["restart"]),
                         ("postgres:16.8", True, "always"))
        self.assertNotIn("live-db-pre-16.8", self.host.containers)

    def assert_old_server_checked_before_odoo(self):
        """The old server was started, then asked, then Odoo came back."""
        calls = self.host.calls
        started = max(i for i, c in enumerate(calls) if c == ["docker", "start", "live-db"])
        asked = max(i for i, c in enumerate(calls) if "pg_isready" in c)
        odoo = calls.index(["docker", "start", "live-odoo"])
        self.assertLess(started, asked)
        self.assertLess(asked, odoo)

    def compose_target(self):
        compose = os.path.join(self.tmp, "docker-compose.yml")
        original = "services:\n  postgres:\n    image: postgres:16.8\n"
        with open(compose, "w") as handle:
            handle.write(original)
        self.host = Host(compose_owned=True)
        tgt = self.legacy_target(kind="compose", compose_file=compose, compose_service="postgres")
        return tgt, compose, original


class UpdateOneTest(UpdateCase):
    def test_legacy_happy_path_order(self):
        plan = self.plan()
        self.assertEqual(self.update(plan), 0)
        self.assertEqual(self.host.changes(), [
            ["docker", "stop", "live-odoo"],
            ["<backup>"],
            ["docker", "stop", "live-db"],
            ["docker", "rename", "live-db", "live-db-pre-16.8"],
            ["docker", "update", "--restart=no", "live-db-pre-16.8"],
            ["docker", "compose", "-f", plan.compose_file, "up", "-d"],
            ["docker", "start", "live-odoo"]])
        with open(plan.compose_file) as handle:
            self.assertEqual(handle.read(), plan.compose_text)
        self.assertEqual(os.stat(plan.compose_file).st_mode & 0o777, 0o600)
        parked = self.host.containers["live-db-pre-16.8"]
        self.assertEqual((parked["running"], parked["restart"]), (False, "no"))
        text = self.text()
        for expected in ("16.8", "16.16", "pgup --rollback live-db",
                         "docker rm live-db-pre-16.8", plan.compose_file, "/opt/backups"):
            self.assertIn(expected, text)
        # the new server was checked before Odoo came back
        ready = max(i for i, c in enumerate(self.host.calls) if "pg_isready" in c)
        self.assertLess(ready, self.host.calls.index(["docker", "start", "live-odoo"]))

    def test_state_file_exists_before_the_rename(self):
        seen = {}

        def hook(argv):
            if argv[:3] == ["docker", "stop", "live-db"]:
                seen["before_stop"] = os.path.exists(self.state_file())
            if argv[:2] == ["docker", "rename"]:
                path = self.state_file()
                seen["exists"] = os.path.exists(path)
                seen["mode"] = os.stat(path).st_mode & 0o777
                seen["dir"] = os.stat(os.path.dirname(path)).st_mode & 0o777
                with open(path) as handle:
                    seen["state"] = json.load(handle)

        self.host.hooks.append(hook)
        self.assertEqual(self.update(self.plan()), 0)
        self.assertTrue(seen["before_stop"])
        self.assertEqual((seen["exists"], seen["mode"], seen["dir"]), (True, 0o600, 0o700))
        state = seen["state"]
        self.assertEqual((state["name"], state["kind"], state["old_image"], state["new_image"],
                          state["old_version"], state["new_version"], state["parked_name"],
                          state["parked_restart"], state["stopped_odoo"]),
                         ("live-db", "legacy", "postgres:16.8", "postgres:16.16-bookworm",
                          "16.8", "16.16", "live-db-pre-16.8", "always", ["live-odoo"]))
        self.assertTrue(state["compose_file"].endswith("docker-compose.yml"))
        self.assertIsNone(state["compose_backup"])
        self.assertIn("time", state)

    def test_only_previously_running_odoo_is_started(self):
        tgt = self.legacy_target(odoo=[odoo_info(), odoo_info(name="old-odoo", running=False)])
        self.assertEqual(self.update(self.plan(tgt=tgt)), 0)
        self.assertTrue(self.started("live-odoo"))
        self.assertFalse(self.started("old-odoo"))
        self.assertNotIn(["docker", "stop", "old-odoo"], self.host.calls)

    def test_failed_backup_restarts_odoo_and_touches_no_database(self):
        self.backup_result = (False, [])
        self.assertEqual(self.update(self.plan()), 1)
        self.assertEqual(self.host.changes(), [
            ["docker", "stop", "live-odoo"], ["<backup>"], ["docker", "start", "live-odoo"]])
        self.assertNotIn(["docker", "stop", "live-db"], self.host.calls)
        self.assertFalse(os.path.exists(self.state_file()))

    def test_failed_odoo_stop_starts_them_again_and_stops_there(self):
        self.host.fail[("docker", "stop", "live-odoo")] = (1, "timeout")
        self.assertEqual(self.update(self.plan()), 1)
        self.assertNotIn("<backup>", [c[0] for c in self.host.calls])
        self.assertNotIn(["docker", "stop", "live-db"], self.host.calls)
        self.assertTrue(self.started("live-odoo"))

    def test_new_server_not_ready_is_undone(self):
        self.host.not_ready.add("postgres:16.16-bookworm")
        plan = self.plan()
        self.assertEqual(self.update(plan), 1)
        self.assertEqual(self.host.changes()[3:], [
            ["docker", "rename", "live-db", "live-db-pre-16.8"],
            ["docker", "update", "--restart=no", "live-db-pre-16.8"],
            ["docker", "compose", "-f", plan.compose_file, "up", "-d"],
            ["docker", "compose", "-f", plan.compose_file, "down"],
            ["docker", "rename", "live-db-pre-16.8", "live-db"],
            ["docker", "update", "--restart=always", "live-db"],
            ["docker", "start", "live-db"],
            ["docker", "start", "live-odoo"]])
        self.assert_old_server_back()
        self.assert_old_server_checked_before_odoo()
        self.assertFalse(os.path.exists(self.state_file()))     # archived, not left behind
        self.assertTrue(any(f.startswith("live-db.json.undone-")
                            for f in os.listdir(os.path.dirname(self.state_file()))))

    def test_database_list_changed_is_undone(self):
        self.host.databases_switched = "postgres\n"
        self.assertEqual(self.update(self.plan()), 1)
        self.assert_old_server_back()
        self.assertTrue(self.started("live-odoo"))
        self.assertIn("databases", self.text())

    def test_wrong_version_after_the_switch_is_undone(self):
        self.host.versions["postgres:16.16-bookworm"] = "16.9"
        self.assertEqual(self.update(self.plan()), 1)
        self.assert_old_server_back()

    def test_failing_compose_up_is_undone(self):
        plan = self.plan()
        self.host.fail[("docker", "compose", "-f", plan.compose_file, "up")] = (1, "boom")
        self.assertEqual(self.update(plan), 1)
        self.assert_old_server_back()
        self.assertTrue(self.started("live-odoo"))

    def test_failing_stop_of_the_database_is_undone_without_a_rename(self):
        self.host.fail[("docker", "stop", "live-db")] = (1, "busy")
        self.assertEqual(self.update(self.plan()), 1)
        self.assertFalse(any(c[:2] == ["docker", "rename"] for c in self.host.calls))
        self.assert_old_server_back()
        self.assertTrue(self.started("live-odoo"))

    def test_failing_rename_is_undone(self):
        self.host.fail[("docker", "rename", "live-db")] = (1, "denied")
        self.assertEqual(self.update(self.plan()), 1)
        self.assert_old_server_back()
        self.assertFalse(os.path.exists(os.path.join(self.deploy, "docker-compose.yml")))

    def test_undo_that_fails_names_the_containers_and_leaves_odoo_stopped(self):
        plan = self.plan()
        self.host.not_ready.add("postgres:16.16-bookworm")
        self.host.fail[("docker", "compose", "-f", plan.compose_file, "down")] = (1, "stuck")
        self.assertEqual(self.update(plan), 2)
        self.assertFalse(self.started("live-odoo"))
        text = self.text()
        self.assertIn("live-db: running, image postgres:16.16-bookworm", text)
        self.assertIn("live-db-pre-16.8: stopped, image postgres:16.8", text)
        self.assertIn("Odoo stays stopped", text)
        self.assertTrue(os.path.exists(self.state_file()))

    def test_collation_mismatch_keeps_odoo_down(self):
        self.host.collation_switched = "live_db\n"
        self.assertEqual(self.update(self.plan()), 2)
        self.assertFalse(self.started("live-odoo"))
        text = self.text()
        self.assertIn("pgup --rollback live-db", text)
        self.assertIn("REFRESH COLLATION VERSION", text)
        self.assertIn("REINDEX", text)
        self.assertTrue(self.host.containers["live-db"]["running"])
        self.assertEqual(self.host.containers["live-db"]["image"], "postgres:16.16-bookworm")

    def test_collation_mismatch_that_existed_before_does_not_block(self):
        simulate = self.host.simulate

        def answer(argv):
            if argv[:2] == ["docker", "exec"] and "datcollversion" in argv[-1]:
                return 0, "live_db\n"
            return simulate(argv)

        self.host.simulate = answer
        self.assertEqual(self.update(self.plan()), 0)
        self.assertTrue(self.started("live-odoo"))

    def test_compose_managed_path_backs_up_and_patches_the_file(self):
        tgt, compose, original = self.compose_target()
        plan = self.plan(tgt=tgt)
        self.assertEqual(self.update(plan), 0)
        self.assertEqual(self.host.changes(), [
            ["docker", "stop", "live-odoo"],
            ["<backup>"],
            ["docker", "stop", "live-db"],
            ["docker", "compose", "-f", compose, "up", "-d"],
            ["docker", "start", "live-odoo"]])
        with open(compose) as handle:
            self.assertEqual(handle.read(), plan.compose_text)
        backups = [f for f in os.listdir(self.tmp) if f.startswith("docker-compose.yml.bak-")]
        self.assertEqual(len(backups), 1)
        bak = os.path.join(self.tmp, backups[0])
        with open(bak) as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(os.stat(bak).st_mode & 0o777, 0o600)
        with open(self.state_file()) as handle:
            self.assertEqual(json.load(handle)["compose_backup"], bak)
        self.assertEqual(self.host.containers["live-db"]["image"], "postgres:16.16-bookworm")
        self.assertNotIn("docker rm", self.text())

    def test_compose_managed_failure_restores_the_file_and_recreates(self):
        tgt, compose, original = self.compose_target()
        self.host.not_ready.add("postgres:16.16-bookworm")
        self.assertEqual(self.update(self.plan(tgt=tgt)), 1)
        with open(compose) as handle:
            self.assertEqual(handle.read(), original)
        self.assert_old_server_back()
        self.assertTrue(self.started("live-odoo"))

    def test_conversion_only_plan_keeps_the_version(self):
        self.host.versions["postgres:16.8"] = "16.8"
        plan = self.plan(choice=CURRENT)
        self.assertEqual(self.update(plan), 0)
        self.assertEqual(self.host.containers["live-db"]["image"], "postgres:16.8")
        self.assertTrue(self.host.containers["live-db"]["compose"])
        self.assertTrue(self.started("live-odoo"))
        archived = os.listdir(os.path.dirname(self.state_file()))
        self.assertEqual(archived, ["live-db.json"])
        with open(self.state_file()) as handle:
            state = json.load(handle)
        self.assertEqual((state["old_version"], state["new_version"]), ("16.8", "16.8"))

    def test_sizing_refusal_does_not_change_the_exit_code(self):
        sizing = pg._need("ownerp_sizing")
        seen = {}

        def refuse(db, recommended, overrides, state_entry, run, user, **kw):
            seen["args"] = (db, recommended, overrides, user)
            return sizing.PgSync(False, [], False, None, True, "refused: shared_buffers", None)

        self.patch(sizing, "sync_postgres", refuse)
        plan = self.plan()
        plan.sizing = pg.SizingView({"shared_buffers": "2GB"}, {}, {}, None, {"shared_buffers"})
        self.assertEqual(self.update(plan, opts=self.options(sizing="apply")), 0)
        self.assertEqual(seen["args"], ("live-db", {"shared_buffers": "2GB"},
                                        {"shared_buffers"}, "ownerp"))
        self.assertIn("refused: shared_buffers", self.text())
        self.assertTrue(self.started("live-odoo"))

    def test_sizing_state_is_kept_under_pg_deploy_for_an_unmanaged_instance(self):
        sizing = pg._need("ownerp_sizing")

        def write(db, recommended, overrides, state_entry, run, user, **kw):
            state_entry["shared_buffers"] = {"status": "accepted", "known": ["2GB"]}
            return sizing.PgSync(True, [], True, True, False, None, None)

        self.patch(sizing, "sync_postgres", write)
        plan = self.plan()
        plan.sizing = pg.SizingView({"shared_buffers": "2GB"}, {}, {}, None)
        self.assertEqual(self.update(plan, opts=self.options(sizing="apply")), 0)
        path = os.path.join(self.tmp, "pg-deploy", "state", "live-db.sizing.json")
        with open(path) as handle:
            self.assertEqual(json.load(handle)["pg"]["shared_buffers"]["known"], ["2GB"])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_sizing_state_of_a_managed_instance_lives_in_its_build_dir(self):
        sizing = pg._need("ownerp_sizing")
        build = os.path.join(self.tmp, "build")
        os.makedirs(build)
        cfg = os.path.join(self.tmp, "update.yaml")
        with open(cfg, "w") as handle:
            yaml.safe_dump({"containers": [{"container_name": "live-odoo", "db_host": "live-db",
                                            "dockerfile_path": build,
                                            "sizing": {"profile": "live"}}]}, handle)

        def write(db, recommended, overrides, state_entry, run, user, **kw):
            state_entry["shared_buffers"] = {"status": "accepted", "known": ["2GB"]}
            return sizing.PgSync(True, [], True, True, False, None, None)

        self.patch(sizing, "sync_postgres", write)
        plan = self.plan()
        plan.sizing = pg.SizingView({"shared_buffers": "2GB"}, {}, {}, None)
        opts = pg.Options(home=self.tmp, sizing="apply", update_config=cfg,
                          backup_config=self.opts.backup_config)
        self.assertEqual(self.update(plan, opts=opts), 0)
        saved, problem = sizing.load_state(build)
        self.assertIsNone(problem)
        self.assertEqual(saved["pg"]["shared_buffers"]["known"], ["2GB"])
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, "pg-deploy", "state", "live-db.sizing.json")))

    def test_sizing_in_show_mode_is_not_applied(self):
        sizing = pg._need("ownerp_sizing")
        self.patch(sizing, "sync_postgres", lambda *a, **k: self.fail("must not run"))
        plan = self.plan()
        plan.sizing = pg.SizingView({"shared_buffers": "2GB"}, {}, {}, None)
        self.assertEqual(self.update(plan), 0)

    def test_dry_run_changes_nothing(self):
        plan = self.plan()
        self.assertEqual(self.update(plan, opts=self.options(dry_run=True)), 0)
        self.assertEqual(self.host.calls, [])
        self.assertIn("Compose file", self.text())
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(plan.compose_file))

    def test_plan_with_problems_starts_nothing(self):
        plan, _ = self.prepare(tgt=self.legacy_target(pgdata=None))
        self.assertEqual(self.update(plan), 2)
        self.assertEqual(self.host.calls, [])
        self.assertIn("data directory not found", self.text())

    def test_old_backup_directories_are_reported_and_kept(self):
        old = os.path.join(self.deploy, "pre-update", "20260101-000000")
        os.makedirs(old)
        with open(os.path.join(old, "a.dump"), "wb") as handle:
            handle.write(b"x" * 2048)
        self.assertEqual(self.update(self.plan()), 0)
        self.assertIn("1 older", self.text())
        self.assertTrue(os.path.isfile(os.path.join(old, "a.dump")))

    def test_vector_extension_update_is_reported_not_run(self):
        image = "postgres-pgvector:16.8-bookworm"
        tgt = self.legacy_target(vector=True, image=image)
        choice = pg.Choice("postgres-pgvector:16.16-bookworm", (16, 16), "x")
        host = Host(old=image, new="postgres-pgvector:16.16-bookworm")
        simulate = host.simulate

        def answer(argv):
            if argv[:2] == ["docker", "exec"]:
                if "pg_available_extensions" in argv[-1]:
                    return 0, "0.8.0\n"
                if "pg_extension" in argv[-1]:
                    return 0, "0.7.4\n"
            return simulate(argv)

        host.simulate = answer
        self.host = host
        prep = self.runner({("docker", "image", "inspect", image): (0, json.dumps([IMAGE])),
                            ("docker", "build"): (0, "")})
        plan, _ = self.prepare(tgt=tgt, choice=choice, run=prep)
        self.assertEqual(plan.problems, [])
        self.assertEqual(self.update(plan), 0)
        self.assertIn("ALTER EXTENSION vector UPDATE", self.text())
        self.assertIn("0.7.4", self.text())
        self.assertFalse(any("ALTER EXTENSION" in " ".join(c) for c in host.calls))


class PhaseTwoHelpersTest(Phase1Case):
    def test_facts_reads_version_databases_and_owner(self):
        answers = {psql("live-db", "ownerp"): (0, "16.8\n"),
                   LIST_DBS: (0, "b\ntemplate1\npostgres\na\n")}
        found = pg.facts("live-db", "ownerp", self.data, FakeRunner(answers))
        stat = os.stat(self.data)
        self.assertEqual(found, {"version": (16, 8), "databases": ["a", "b"],
                                 "owner": "%d:%d" % (stat.st_uid, stat.st_gid)})

    def test_facts_without_access_to_the_data_directory_has_no_owner(self):
        found = pg.facts("live-db", "ownerp", os.path.join(self.tmp, "gone"), FakeRunner())
        self.assertIsNone(found["owner"])
        self.assertIsNone(found["version"])
        self.assertIsNone(found["databases"])

    def test_wait_ready_retries_then_gives_up(self):
        sleeps = []
        run = FakeRunner()
        self.assertFalse(pg.wait_ready("live-db", "ownerp", run, sleep=sleeps.append, retries=3))
        self.assertEqual(len(run.calls), 3)
        self.assertEqual(sleeps, [5, 5])
        run = FakeRunner({("docker", "exec", "live-db", "pg_isready", "-U", "ownerp",
                           "-d", "postgres"): (0, "")})
        self.assertTrue(pg.wait_ready("live-db", "ownerp", run, sleep=sleeps.append))

    def test_state_path(self):
        self.assertEqual(pg.state_path("/root", "live-db"), "/root/pg-deploy/state/live-db.json")


class RollbackTest(UpdateCase):
    def setUp(self):
        super().setUp()
        self.now = datetime.datetime(2026, 11, 18, 12, 0, 0)
        self.patch(pg, "discover", lambda run, cfg, user=None: [self.legacy_target(
            odoo=[odoo_info()])])

    def updated(self, tgt=None):
        self.assertEqual(self.update(self.plan(tgt=tgt)), 0)
        self.host.calls.clear()
        self.lines.clear()

    def set_age(self, days):
        with open(self.state_file()) as handle:
            state = json.load(handle)
        state["time"] = (self.now - datetime.timedelta(days=days)).isoformat()
        with open(self.state_file(), "w") as handle:
            json.dump(state, handle)

    def rollback(self, ask=None, opts=None, name="live-db"):
        return pg.rollback(name, opts or self.opts, self.host, self.lines.append, now=self.now,
                           ask=ask, sleep=lambda seconds: None)

    def test_rollback_legacy(self):
        self.updated()
        self.set_age(1)
        self.assertEqual(self.rollback(), 0)
        compose_file = os.path.join(self.deploy, "docker-compose.yml")
        self.assertEqual(self.host.changes(), [
            ["docker", "stop", "live-odoo"],
            ["docker", "compose", "-f", compose_file, "down"],
            ["docker", "rename", "live-db-pre-16.8", "live-db"],
            ["docker", "update", "--restart=always", "live-db"],
            ["docker", "start", "live-db"],
            ["docker", "start", "live-odoo"]])
        self.assert_old_server_back()
        self.assert_old_server_checked_before_odoo()
        names = os.listdir(os.path.dirname(self.state_file()))
        self.assertEqual(names, ["live-db.json.rolled-back-20261118-120000"])

    def test_rollback_does_not_start_an_odoo_that_was_stopped(self):
        self.updated()
        self.set_age(1)
        self.host.containers["live-odoo"]["running"] = False
        self.patch(pg, "discover", lambda run, cfg, user=None: [self.legacy_target(
            odoo=[odoo_info(running=False)])])
        self.assertEqual(self.rollback(), 0)
        self.assertFalse(self.started("live-odoo"))

    def test_rollback_without_state_says_so(self):
        self.assertEqual(self.rollback(), 2)
        self.assertEqual(self.host.calls, [])
        self.assertIn(self.state_file(), self.text())

    def test_rollback_without_parked_container_stops(self):
        self.updated()
        self.set_age(1)
        del self.host.containers["live-db-pre-16.8"]
        self.assertEqual(self.rollback(), 2)
        self.assertEqual(self.host.changes(), [])
        self.assertIn("live-db-pre-16.8", self.text())
        self.assertTrue(os.path.exists(self.state_file()))

    def test_rollback_compose_without_backup_file_stops(self):
        tgt, compose, original = self.compose_target()
        self.updated(tgt=tgt)
        self.set_age(1)
        for name in os.listdir(self.tmp):
            if ".bak-" in name:
                os.rename(os.path.join(self.tmp, name), os.path.join(self.tmp, "moved-away"))
        self.assertEqual(self.rollback(), 2)
        self.assertEqual(self.host.changes(), [])

    def test_rollback_compose_restores_the_file(self):
        tgt, compose, original = self.compose_target()
        self.updated(tgt=tgt)
        self.set_age(1)
        self.assertEqual(self.rollback(), 0)
        with open(compose) as handle:
            self.assertEqual(handle.read(), original)
        self.assert_old_server_back()
        self.assertTrue(self.started("live-odoo"))

    def test_rollback_after_seven_days_needs_force_without_terminal(self):
        self.updated()
        self.set_age(8)
        self.assertEqual(self.rollback(), 2)                  # no terminal, no force
        self.assertEqual(self.host.changes(), [])
        self.assertEqual(self.rollback(opts=self.options(no_input=True), ask=lambda q: True), 2)
        self.assertEqual(self.host.changes(), [])
        self.assertEqual(self.rollback(opts=self.options(no_input=True, force=True)), 0)
        self.assert_old_server_back()

    def test_rollback_after_seven_days_asks_on_a_terminal(self):
        self.updated()
        self.set_age(8)
        questions = []
        self.assertEqual(self.rollback(ask=lambda q: questions.append(q) or False), 2)
        self.assertEqual(len(questions), 1)
        self.assertIn("8 days", questions[0])
        self.assertEqual(self.host.changes(), [])
        self.assertEqual(self.rollback(ask=lambda q: True), 0)

    def test_rollback_that_does_not_come_up_leaves_odoo_stopped(self):
        self.updated()
        self.set_age(1)
        self.host.not_ready.add("postgres:16.8")
        self.assertEqual(self.rollback(), 2)
        self.assertFalse(self.started("live-odoo"))
        self.assertTrue(os.path.exists(self.state_file()))
        self.assertIn("live-db", self.text())

    def test_rollback_with_wrong_version_leaves_odoo_stopped(self):
        self.updated()
        self.set_age(1)
        self.host.versions["postgres:16.8"] = "16.1"
        self.assertEqual(self.rollback(), 2)
        self.assertFalse(self.started("live-odoo"))


if __name__ == "__main__":
    unittest.main()

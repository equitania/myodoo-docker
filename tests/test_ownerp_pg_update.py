"""
Tests for discovery, version, base and update choice of ownerp_pg_update.py.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_pg_update -v
"""

import datetime
import json
import os
import sys
import unittest

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
                                          "blocked": None})
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


if __name__ == "__main__":
    unittest.main()

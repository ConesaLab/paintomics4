#!/usr/bin/env python3
"""Installer smoke test: a real species install into a scratch environment.

Drives DBManager's command functions in subprocesses (the scriptine CLI
wrapper cannot run on Python 3.11, and the command functions end in CLI
exit() calls -- exit(0) on success -- so each gets its own interpreter,
exactly like an operator's shell) through the same two commands:

    download --specie=<sp> --kegg=1 --mapping=1 --common=0 --reactome=0
    install  --specie=<sp> --common=0 --hub=0

into a KEGG_DATA tree and a mongod that this script creates and owns, then
asserts what an operator would check by hand:

  * the download stages kgml/, mapping/, the three .list files and VERSION;
  * the install promotes the staged tree into current/<sp> without losing it;
  * the species database holds sane, nonzero collections;
  * findIDsByFeaturesName resolves a real gene symbol from the fresh install
    to its KEGG id, through the production mapper code.

Everything lives under --scratch: the mongod dbpath, its log, and the
KEGG_DATA tree. The script refuses to run against port 27017 so it can
never touch a development or production MongoDB, and every subprocess
gets PAINTOMICS_KEGG_DATA pointing into --scratch, never at a real tree.

The one thing a species install cannot produce for itself is the common
KEGG data (pathway classification, organism names, reference PNGs):
downloading it takes hours of polite 2-second requests, so the smoke
COPIES current/common read-only from an existing tree (--seed-common;
in CI that is the restored $PAINTOMICS_KEGG_DATA snapshot). The seed is
only ever read; the install runs entirely inside the scratch copy.

Species: mge (Mycoplasma genitalium) by default -- the smallest KEGG
organism, ~59 pathways, ~5 minutes of polite (2 s delay) downloading.

Usage:
    python scripts/ci/installer_smoke.py --scratch /tmp/installer-smoke \
        --seed-common "$PAINTOMICS_KEGG_DATA" [--species mge] [--port 27777]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ADMIN = os.path.join(REPO, "PaintomicsServer", "src", "AdminTools")
SERVER = os.path.join(REPO, "PaintomicsServer")

# Sane floors for the smallest KEGG organism; a real install of anything
# can only be larger. Zero in any of these means the fail-soft installer
# "succeeded" without data -- exactly the failure this smoke exists to catch.
MIN_PATHWAYS = 30
MIN_XREFS = 500
MIN_DBNAMES = 4


def fail(msg):
    print("SMOKE FAIL: " + msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scratch", required=True,
                        help="directory this script may create and fill; never the real KEGG_DATA")
    parser.add_argument("--seed-common", required=True,
                        help="existing KEGG_DATA tree whose current/common is copied "
                             "(read-only source) into the scratch; a species build "
                             "needs the pathway classification it holds")
    parser.add_argument("--species", default="mge")
    parser.add_argument("--port", type=int, default=27777)
    parser.add_argument("--mongod", default="mongod")
    args = parser.parse_args()

    if args.port == 27017:
        fail("refusing to run against the default MongoDB port; pick a scratch port")

    scratch = os.path.abspath(args.scratch)
    kegg_data = os.path.join(scratch, "KEGG_DATA")
    dbpath = os.path.join(scratch, "mongo")
    for d in (os.path.join(kegg_data, "download"), os.path.join(kegg_data, "current"), dbpath):
        os.makedirs(d, exist_ok=True)

    seed = os.path.join(os.path.abspath(args.seed_common), "current", "common")
    if not os.path.isfile(os.path.join(seed, "pathways_classification.list")):
        fail("--seed-common %r has no current/common/pathways_classification.list" % args.seed_common)
    target = os.path.join(kegg_data, "current", "common")
    if not os.path.isdir(target):
        # cp -c clones instantly on APFS; fall back to a plain copy elsewhere.
        if subprocess.run(["cp", "-c", "-R", seed, target],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            shutil.copytree(seed, target)
    print("smoke: seeded current/common from %s" % seed)

    # The mapper and DBManager read the target environment at import time.
    os.environ["PAINTOMICS_KEGG_DATA"] = kegg_data
    os.environ["MONGODB_HOST"] = "localhost"
    os.environ["MONGODB_PORT"] = str(args.port)

    conf = os.path.join(SERVER, "src", "conf", "serverconf.py")
    if not os.path.exists(conf):
        shutil.copy(os.path.join(SERVER, "src", "resources", "example_serverconf.py"), conf)

    mongod = subprocess.Popen(
        [args.mongod, "--dbpath", dbpath, "--port", str(args.port),
         "--bind_ip", "127.0.0.1", "--logpath", os.path.join(scratch, "mongod.log")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        from pymongo import MongoClient
        client = None
        for _ in range(30):
            try:
                client = MongoClient("localhost", args.port, serverSelectionTimeoutMS=1000)
                client.admin.command("ping")
                break
            except Exception:
                time.sleep(1)
        else:
            fail("scratch mongod did not come up on port %d" % args.port)
        print("smoke: scratch mongod up on %d, KEGG_DATA at %s" % (args.port, kegg_data))

        sp = args.species

        def dbmanager(call):
            # DBManager expects to run from its own directory (conf. and
            # scripts. imports are cwd-relative there), and its command
            # functions finish with exit(0)/exit(n) like the CLI they are --
            # hence one subprocess per command, success meaning exit code 0.
            code = ("import sys; sys.path.insert(0, '.'); "
                    "import DBManager; DBManager." + call)
            proc = subprocess.run([sys.executable, "-c", code],
                                  cwd=ADMIN, env=os.environ.copy())
            if proc.returncode != 0:
                fail("%s exited %d" % (call, proc.returncode))

        print("smoke: downloading %s from KEGG (kegg=1 mapping=1) ..." % sp)
        dbmanager("download_command(specie=%r, kegg=1, mapping=1, common=0, reactome=0)" % sp)

        staged = os.path.join(kegg_data, "download", sp)
        for artefact in ("kgml", "mapping", "gene2pathway.list",
                         "pathway2gene.list", "pathways.list", "VERSION"):
            if not os.path.exists(os.path.join(staged, artefact)):
                fail("download did not stage %s/%s" % (sp, artefact))
        print("smoke: download staged all artefacts")

        print("smoke: installing %s ..." % sp)
        dbmanager("install_command(specie=%r, common=0, hub=0)" % sp)

        if not os.path.isdir(os.path.join(kegg_data, "current", sp, "kgml")):
            fail("install did not promote download/%s into current/" % sp)
        if os.path.isdir(staged):
            fail("install left a stale staged copy in download/%s" % sp)

        db = client[sp + "-paintomics"]
        counts = {c: db[c].count_documents({}) for c in db.list_collection_names()}
        print("smoke: collections " + repr(counts))
        if counts.get("kegg", 0) < MIN_PATHWAYS:
            fail("kegg has %d pathways, floor is %d" % (counts.get("kegg", 0), MIN_PATHWAYS))
        if counts.get("xref", 0) < MIN_XREFS:
            fail("xref has %d entries, floor is %d" % (counts.get("xref", 0), MIN_XREFS))
        if counts.get("dbname", 0) < MIN_DBNAMES:
            fail("dbname has %d entries, floor is %d" % (counts.get("dbname", 0), MIN_DBNAMES))

        # A real identifier through the production mapper. The translation
        # cache singleton needs the full server config; the mapper only uses
        # it as a cache, so a null cache keeps the query path honest.
        sys.path.insert(0, SERVER)
        from src.common import FeatureNamesToKeggIDsMapper as mapper

        class _NoCache(object):
            def findBatchInTranslationCache(self, *a, **k):
                return {}

            def updateTranslationCache(self, *a, **k):
                return None

        mapper.KeggInformationManager = lambda: _NoCache()

        symbol_db = db.dbname.find_one({"dbname": "kegg_gene_symbol"})
        kegg_db = db.dbname.find_one({"dbname": "kegg_id"})
        if not symbol_db or not kegg_db:
            fail("dbname is missing kegg_gene_symbol or kegg_id")
        probe = db.xref.find_one({"dbname_id": symbol_db["_id"]})
        if not probe:
            fail("no gene-symbol xref to probe with")
        symbol = probe["display_id"]
        result = mapper.findIDsByFeaturesName("smoke", [symbol], db, kegg_db["_id"])
        if not result.get(symbol):
            fail("findIDsByFeaturesName resolved nothing for %r" % symbol)
        print("smoke: mapper resolved %r -> %r" % (symbol, result[symbol]))
        print("SMOKE PASS: %s installed, %d pathways, %d xrefs, mapper resolves"
              % (sp, counts["kegg"], counts["xref"]))
    finally:
        mongod.terminate()
        mongod.wait(timeout=30)


if __name__ == "__main__":
    main()

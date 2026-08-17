from src.common.DAO.DAO import DAO
from datetime import datetime

class AIInterpretDAO(DAO):
    def __init__(self, *args, **kwargs):
        super(AIInterpretDAO, self).__init__(*args, **kwargs)
        self.collectionName = "aiInterpretationCollection"

    def save_progress(self, job_id, data):
        """Upsert progress/report for a job."""
        collection = self.dbManager.getCollection(self.collectionName)
        data["updatedAt"] = datetime.utcnow()
        collection.update_one(
            {"jobID": job_id},
            {"$set": data, "$setOnInsert": {"createdAt": datetime.utcnow()}},
            upsert=True
        )

    def touch(self, job_id):
        """Update only the updatedAt timestamp (used by heartbeat)."""
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$set": {"updatedAt": datetime.utcnow()}}
        )

    def find_by_job_id(self, job_id):
        collection = self.dbManager.getCollection(self.collectionName)
        return collection.find_one({"jobID": job_id})

    def save_papers(self, job_id, papers):
        """Store collected PubMed papers for a job."""
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$set": {"papers": papers, "updatedAt": datetime.utcnow()}},
            upsert=True
        )

    def append_tool_event(self, job_id, event):
        """Append one agent tool-call event to the job's toolTrace.

        Capped at the last 200 events so a chatty run cannot grow the
        document without bound; the full trace lives in the server log.
        """
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$push": {"toolTrace": {"$each": [event], "$slice": -200}},
             "$set": {"updatedAt": datetime.utcnow()}},
            upsert=True
        )

    def append_chat(self, job_id, role, content):
        """Append a message to conversation history."""
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$push": {"conversation": {"role": role, "content": content,
                                         "timestamp": datetime.utcnow()}}}
        )

    def get_paper_by_ref_index(self, job_id, ref_index):
        """Retrieve a single paper by its ref_index using $elemMatch projection."""
        collection = self.dbManager.getCollection(self.collectionName)
        doc = collection.find_one(
            {"jobID": job_id, "papers.ref_index": ref_index},
            {"papers": {"$elemMatch": {"ref_index": ref_index}}}
        )
        if doc and doc.get("papers"):
            return doc["papers"][0]
        return None

    def save_pathway_index(self, job_id, pathways):
        """Store the pathways the report was written from.

        The report names pathways in prose; the client needs id/name/source to
        turn those names into links. build_pathway_context() already assembles
        exactly this, but it was previously fed to the prompts and discarded.
        Only the display fields are kept -- the per-omic detail stays out of the
        document, which is already large.
        """
        index = [
            {"id": pw.get("id"), "name": pw.get("name"), "source": pw.get("source"),
             "combined_pvalue": pw.get("combined_pvalue"),
             "matched_gene_count": pw.get("matched_gene_count")}
            for pw in pathways if pw.get("id") and pw.get("name")
        ]
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$set": {"pathwayIndex": index, "updatedAt": datetime.utcnow()}},
            upsert=True
        )

    def get_pathway_index(self, job_id):
        collection = self.dbManager.getCollection(self.collectionName)
        doc = collection.find_one({"jobID": job_id}, {"pathwayIndex": 1})
        return (doc or {}).get("pathwayIndex", []) or []

    def save_clusters(self, job_id, partition):
        """Store the shared-feature pathway partition the report was written
        from (cluster mode only): clusters with member ids, shared-core
        symbols and hub flag, plus the standalone / further pathway ids and
        the parameters. Compact by design -- ranks and p-values are already
        in pathwayIndex, and feature keys stay out of the document."""
        clusters = [
            {"id": c.get("id"), "label": c.get("label"),
             "members": list(c.get("members") or []),
             "satellites": list(c.get("satellites") or []),
             "core": [f.get("symbol") for f in (c.get("core") or [])],
             "hub_driven": bool(c.get("hub_driven")),
             "sources": list(c.get("sources") or [])}
            for c in (partition.get("clusters") or [])
        ]
        doc = {"method": partition.get("method"), "version": partition.get("version"),
               "params": {k: v for k, v in (partition.get("params") or {}).items()},
               "nodes": len(partition.get("nodes") or []),
               "clusters": clusters,
               "standalone": list(partition.get("standalone") or []),
               "further": list(partition.get("further") or [])}
        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"jobID": job_id},
            {"$set": {"clusters": doc, "updatedAt": datetime.utcnow()}},
            upsert=True
        )

    def get_clusters(self, job_id):
        collection = self.dbManager.getCollection(self.collectionName)
        doc = collection.find_one({"jobID": job_id}, {"clusters": 1})
        return (doc or {}).get("clusters") or None

    def get_pathway_report(self, job_id, pathway_id):
        """Return a cached per-pathway interpretation, or None.

        Stored as an array rather than a keyed subdocument because pathway IDs
        are external data -- a key containing "." or a leading "$" would be
        rejected by MongoDB.
        """
        collection = self.dbManager.getCollection(self.collectionName)
        doc = collection.find_one(
            {"jobID": job_id, "pathwayReports.pathwayID": pathway_id},
            {"pathwayReports": {"$elemMatch": {"pathwayID": pathway_id}}}
        )
        if doc and doc.get("pathwayReports"):
            return doc["pathwayReports"][0]
        return None

    def save_pathway_report(self, job_id, pathway_id, report, papers=None):
        """Cache a per-pathway interpretation so a second click is free."""
        entry = {"pathwayID": pathway_id, "report": report,
                 "papers": papers or [], "createdAt": datetime.utcnow()}
        collection = self.dbManager.getCollection(self.collectionName)
        # Drop any previous entry for this pathway first, so a regenerate
        # replaces rather than accumulates duplicates.
        collection.update_one(
            {"jobID": job_id},
            {"$pull": {"pathwayReports": {"pathwayID": pathway_id}}}
        )
        collection.update_one(
            {"jobID": job_id},
            {"$push": {"pathwayReports": entry},
             "$set": {"updatedAt": datetime.utcnow()}},
            upsert=True
        )

    def get_papers_metadata(self, job_id):
        """Retrieve papers without full-text sections (for display/lightweight queries)."""
        collection = self.dbManager.getCollection(self.collectionName)
        doc = collection.find_one(
            {"jobID": job_id},
            {"papers": 1}
        )
        if not doc or not doc.get("papers"):
            return []
        papers = []
        for p in doc["papers"]:
            meta = {k: v for k, v in p.items() if k != "sections"}
            papers.append(meta)
        return papers

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

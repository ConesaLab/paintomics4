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

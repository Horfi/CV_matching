import logging
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from config import QDRANT_URL

logger = logging.getLogger(__name__)

def get_qdrant_client() -> QdrantClient:
    """Returns a connected Qdrant client."""
    return QdrantClient(url=QDRANT_URL, timeout=60.0)


def delete_qdrant_points(job_ids: list):
    """Removes points from Qdrant corresponding to PostgreSQL job IDs."""
    if not job_ids:
        return
    try:
        client = get_qdrant_client()
        client.delete(
            collection_name="job_postings",
            points_selector=job_ids
        )
        logger.info("Deleted %s points from Qdrant index.", len(job_ids))
    except Exception as exc:
        logger.error("Failed to delete points from Qdrant: %s", exc)


def upsert_qdrant_point(job_id: int, vector: list, payload: dict):
    """Uploads/updates a vector point in Qdrant job_postings collection."""
    try:
        client = get_qdrant_client()
        point = PointStruct(
            id=job_id,
            vector=vector,
            payload=payload
        )
        client.upsert(
            collection_name="job_postings",
            points=[point]
        )
        logger.info("Upserted point for job_id %s in Qdrant index.", job_id)
    except Exception as exc:
        logger.error("Failed to upload point to Qdrant: %s", exc)


def query_similar_jobs(vector: list, limit: int = 5, source_ids: list = None) -> list:
    """Queries Qdrant to retrieve most similar jobs matching the CV vector."""
    try:
        client = get_qdrant_client()
        
        query_filter = None
        if source_ids:
            from qdrant_client.models import Filter, FieldCondition, MatchAny
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchAny(any=source_ids)
                    )
                ]
            )
            logger.info("Querying Qdrant with source_ids filter: %s", source_ids)

        query_response = client.query_points(
            collection_name="job_postings",
            query=vector,
            limit=limit,
            query_filter=query_filter
        )
        return query_response.points
    except Exception as exc:
        logger.error("Failed to query similar jobs from Qdrant: %s", exc)
        return []


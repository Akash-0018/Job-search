"""Fake jobs for testing the pipeline offline: python -m src.main --mock --no-llm"""
from ..models import Job

AI_JD = ("We build LLM agents for enterprise customers. You will design RAG pipelines with "
         "embeddings and vector search, build FastAPI services in Python, deploy on AWS Lambda "
         "and Docker, write pytest suites, and integrate tool calling. 1-3 years of experience.")
BACKEND_JD = ("Build multi-tenant SaaS APIs in Python with Django and PostgreSQL, webhooks, "
              "OAuth, Stripe payments, and event-driven microservices on GCP Pub/Sub. 2+ years.")
FDE_JD = ("Work directly with customers to deploy our AI platform: Python integrations, REST "
          "APIs, LLM workflows, and on-site problem solving. 2-4 years of experience.")


def fetch():
    m = "Sample data"
    return [
        Job("AI Engineer", "Sample Labs A", "Bengaluru, Karnataka, India", "https://example.com/1",
            AI_JD, "8-14 Lacs P.A.", "1-3 Yrs", source=m),
        Job("Generative AI Engineer", "Sample Labs B", "Remote, India", "https://example.com/2",
            AI_JD, "", "", source=m, remote=True),
        Job("Python Backend Developer", "Sample SaaS C", "Chennai, Tamil Nadu, India",
            "https://example.com/3", BACKEND_JD, "₹6,00,000 - ₹9,00,000 a year", "2-5 Yrs", source=m),
        Job("Forward Deployed Engineer", "Sample AI D", "Bengaluru", "https://example.com/4",
            FDE_JD, "$20K - $30K", "", source=m),
        Job("Software Engineer - Backend", "Sample Fintech E", "Chennai", "https://example.com/5",
            BACKEND_JD, "", "2-4 years", source=m),
        Job("LLM Engineer", "Sample Labs A", "Bangalore", "https://example.com/6",
            AI_JD, "10-18 LPA", "", source=m),
        # These should all be filtered out:
        Job("Senior AI Engineer", "Sample Labs F", "Bengaluru", "https://example.com/7",
            AI_JD, "30-40 LPA", "6-10 Yrs", source=m),
        Job("Python Developer", "Sample Corp G", "Pune, Maharashtra", "https://example.com/8",
            BACKEND_JD, "8-12 LPA", "", source=m),
        Job("Python Developer", "Sample Corp H", "Chennai", "https://example.com/9",
            BACKEND_JD, "3-5 Lacs P.A.", "", source=m),
        Job("AI Engineer", "Sample Corp I", "Remote - United States only", "https://example.com/10",
            AI_JD, "", "", source=m, remote=True),
        Job("Java Developer", "Sample Corp J", "Chennai", "https://example.com/11",
            "Spring Boot microservices", "", "", source=m),
        Job("Python Developer", "Sample Corp K", "Bengaluru", "https://example.com/12",
            "Python scripting, 5+ years of experience required in automation", "", "", source=m),
    ]

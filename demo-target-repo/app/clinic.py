import httpx

LAB_API = "http://lab-results.medlink.org/api"
LAB_API_SECURE = "https://lab-results.medlink.org/api"


def fetch_lab_results(patient_id: int) -> dict:
    return httpx.get(f"{LAB_API}/results/{patient_id}", timeout=10).json()


def fetch_lab_results_secure(patient_id: int) -> dict:
    return httpx.get(f"{LAB_API_SECURE}/results/{patient_id}", timeout=10).json()

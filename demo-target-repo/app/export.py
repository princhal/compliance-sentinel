import csv
import io

from app.storage import upload_export


def export_customers(customers) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for customer in customers:
        print(f"Exporting customer {customer.email} born {customer.date_of_birth}")
        writer.writerow([customer.id, customer.email])
    upload_export("exports/customers.csv", buf.getvalue().encode())

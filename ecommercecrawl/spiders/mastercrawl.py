from datetime import date
import os
import csv

class Mastercrawl():
    def save_to_csv(self, filename, data):
        filename = f'{filename}.csv'

        # Check if the CSV file exists
        file_exists = os.path.isfile(filename)

        # Append new data to the CSV file
        with open(filename, "a", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=data.keys())

            # Write the header only if the file doesn't exist
            if not file_exists:
                writer.writeheader()

            # Write the data
            writer.writerow(data)

    def save_image(self, response):
        image_dir = response.meta['image_dir']
        filename = response.url.split('/')[-1]
        with open(os.path.join(image_dir, filename), 'wb') as f:
            f.write(response.body)


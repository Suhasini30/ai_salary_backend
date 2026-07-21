import pandas as pd


class DataProcessor:

    def __init__(self, file_path):
        self.file_path = file_path
        self.df = None


    def load_data(self):
        try:
            self.df = pd.read_csv(self.file_path)

            # Fill missing values
            self.df = self.df.fillna({
                "job_title": "Unknown",
                "salary_usd": 0.0,
                "experience_level": "N/A",
                "years_experience": 0,
                "company_location": "Unknown",
                "industry": "Unknown",
                "required_skills": "None listed"
            })

        except Exception as e:
            raise IOError(
                f"Failed to load dataset from {self.file_path}: {e}"
            )

        return self.df


    def validate_data(self):

        if self.df is None:
            raise ValueError(
                "Data has not been loaded. Please call load_data() first."
            )

        required_columns = [
            "job_title",
            "salary_usd",
            "experience_level",
            "years_experience",
            "company_location",
            "industry",
            "required_skills"
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in self.df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"Missing required columns: {', '.join(missing_columns)}"
            )

        return True


    def row_to_chunk(self, row):
        """
        Convert a single dataset row into readable text.
        """

        return (
            f"- Job Role: {row['job_title']}. "
            f"Location: {row['company_location']}. "
            f"Experience Level: {row['experience_level']} "
            f"({row['years_experience']} years). "
            f"Salary: {row['salary_usd']:.0f} USD. "
            f"Industry: {row['industry']}. "
            f"Required Skills: {row['required_skills']}."
        )

    
    def build_row_chunks(self, batch_size=10):

        if self.df is None:
            raise ValueError(
                "Data has not been loaded. Please call load_data() first."
            )

        row_chunks = []

        # Group all rows having the same job title
        grouped = self.df.groupby("job_title")

        for role, group in grouped:

            # Sort postings by salary (highest first)
            group = group.sort_values(
                by="salary_usd",
                ascending=False
            )

            postings = []

            # Convert each row into text
            for _, row in group.iterrows():
                postings.append(
                    self.row_to_chunk(row)
                )

            # Create batches
            for i in range(0, len(postings), batch_size):

                batch = postings[i:i + batch_size]

                chunk_header = (
                    f"Job Role: {role}\n"
                    f"Batch Number: {i // batch_size + 1}\n"
                    f"Number of Postings: {len(batch)}\n"
                    "----------------------------------------\n"
                )

                chunk_body = "\n".join(batch)

                row_chunks.append(
                    chunk_header + chunk_body
                )

        return row_chunks


    def get_all_chunks(self):

        if self.df is None:
            raise ValueError(
                "Data has not been loaded. Please call load_data() first."
            )

        return self.build_row_chunks()
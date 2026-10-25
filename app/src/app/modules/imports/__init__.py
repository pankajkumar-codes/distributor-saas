"""imports: marketplace CSV/Excel uploads, staging rows, validation and
de-duplication. Nothing reaches stock or money until a person confirms the preview.

File reading, header matching, row validation and in-file de-duplication live in
parsing/ (see docs/IMPORTS.md). Marketplace mapping profiles wait on sample
reports from Amazon, Flipkart and Meesho (open question 2).
"""

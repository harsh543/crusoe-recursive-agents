# UCI Online Retail sample attribution

Source: Daqing Chen, *Online Retail*, UCI Machine Learning Repository (2015), DOI: https://doi.org/10.24432/C5BW33

Dataset page: https://archive.ics.uci.edu/dataset/352/online%2Bretail

License: Creative Commons Attribution 4.0 International (CC BY 4.0).

The included `uci_online_retail_sample.csv` is a transformed, deterministic sample of 1,000 rows. Transformations:

- renamed source columns to snake case;
- converted the invoice timestamp to ISO 8601;
- tokenized the published customer identifier with a deterministic SHA-256-derived reference;
- calculated line total and candidate anomaly indicators;
- retained a mix of cancellations, non-positive values, high-price/high-quantity observations, and baseline rows.

`candidate_signal` and `is_anomaly_candidate` are research annotations created for this repository. They are not fraud labels and must not be treated as proof of wrongdoing.


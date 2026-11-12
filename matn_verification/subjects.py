"""Code-owned document subjects. No inferred aliases or pronoun antecedents."""
SUBJECT_REGISTRY_VERSION = 'dev-document-subjects-v1.1'
DOCUMENT_SUBJECTS: dict[str, tuple[str, ...]] = {}

# Bounded explicit geography veto surfaces, not an inferred alias ontology.
FOREIGN_GEOGRAPHIES = ('France', 'Denmark', 'Germany', 'India', 'China',
                       'United States', 'United Kingdom')

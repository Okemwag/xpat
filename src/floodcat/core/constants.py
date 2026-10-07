TIERS = ("extreme", "severe", "moderate", "occasional", "common")
CLASSES = ("informal_iron_sheet", "semi_permanent", "permanent_masonry", "concrete_rcc")
# Spellings people use for the four classes. Mapping is reported back as a warning, never silent.
CLASS_ALIASES = {
    "informal": "informal_iron_sheet", "iron_sheet": "informal_iron_sheet", "mabati": "informal_iron_sheet",
    "informal_iron": "informal_iron_sheet", "shack": "informal_iron_sheet",
    "semipermanent": "semi_permanent", "semi": "semi_permanent", "timber": "semi_permanent",
    "masonry": "permanent_masonry", "permanent": "permanent_masonry", "stone": "permanent_masonry", "brick": "permanent_masonry",
    "concrete": "concrete_rcc", "rcc": "concrete_rcc", "reinforced_concrete": "concrete_rcc", "concrete_frame": "concrete_rcc",
}
# WGS84 bounding extent from Dataset_Metadata.docx; east strip has no raster coverage.
NAIROBI_BOUNDS = (36.60, -1.45, 37.00, -1.10)
MECHANISMS = ("drainage", "surface_runoff", "river_overflow", "other", "unknown")

"""Fictional Indian wholesale data for isolated Vyapro development databases."""

CUSTOMERS = [
    ("DEV-C-001", "Kaveri Provision House", 8_000_000, 2_150_000),
    ("DEV-C-002", "Mahalaxmi General Traders", 6_500_000, 1_830_000),
    ("DEV-C-003", "Shree Balaji Kirana Supply", 5_000_000, 3_950_000),
    ("DEV-C-004", "Deccan Food Distributors", 12_000_000, 4_250_000),
    ("DEV-C-005", "Annapurna Wholesale Stores", 4_000_000, 2_720_000),
    ("DEV-C-006", "Narmada Grocery Depot", 7_500_000, 1_150_000),
    ("DEV-C-007", "Cauvery Rice and Staples", 9_000_000, 5_100_000),
    ("DEV-C-008", "Saffron Valley Traders", 3_500_000, 3_420_000),
]

# Prices are paise per inventory unit. Pack sizes describe the shop pack while
# the authoritative catalog price remains per `unit`, matching current rules.
PRODUCTS = [
    ("DEV-P-001", "VYA-RICE-BAS-25", "India Gate Basmati Rice", "320", "kg", 12_500, "25", "kg", ("basmati", "premium long grain rice")),
    ("DEV-P-002", "VYA-RICE-SON-25", "Sona Masoori Rice", "280", "kg", 7_200, "25", "kg", ("sona masoori", "south indian rice")),
    ("DEV-P-003", "VYA-ATTA-CHA-10", "Chakki Fresh Whole Wheat Atta", "185", "kg", 4_800, "10", "kg", ("atta", "whole wheat flour")),
    ("DEV-P-004", "VYA-DAL-TOOR-25", "Toor Dal Premium", "96", "kg", 13_500, "25", "kg", ("arhar dal", "pigeon pea")),
    ("DEV-P-005", "VYA-DAL-MOONG-25", "Moong Dal Split", "74", "kg", 11_800, "25", "kg", ("yellow moong",)),
    ("DEV-P-006", "VYA-DAL-CHANA-25", "Chana Dal", "112", "kg", 7_400, "25", "kg", ("split chickpeas",)),
    ("DEV-P-007", "VYA-SUGAR-S30-50", "Sugar S-30", "410", "kg", 4_450, "50", "kg", ("sugar", "white sugar")),
    ("DEV-P-008", "VYA-OIL-SUN-15", "Fortune Sunflower Oil", "240", "l", 13_800, "15", "l", ("sunflower oil", "cooking oil")),
    ("DEV-P-009", "VYA-OIL-MUS-15", "Kachi Ghani Mustard Oil", "138", "l", 15_200, "15", "l", ("mustard oil", "sarson oil")),
    ("DEV-P-010", "VYA-TEA-CTC-20", "Assam CTC Tea Dust", "58", "kg", 28_000, "20", "kg", ("tea dust", "ctc tea")),
    ("DEV-P-011", "VYA-SALT-IOD-25", "Iodized Table Salt", "210", "kg", 2_100, "25", "kg", ("salt", "iodized salt")),
    ("DEV-P-012", "VYA-SPICE-TUR-10", "Turmeric Powder", "42", "kg", 18_500, "10", "kg", ("haldi powder", "turmeric")),
    ("DEV-P-013", "VYA-SPICE-CHL-10", "Red Chilli Powder", "31", "kg", 24_000, "10", "kg", ("lal mirch", "chilli powder")),
    ("DEV-P-014", "VYA-SPICE-COR-10", "Coriander Powder", "47", "kg", 12_500, "10", "kg", ("dhania powder",)),
    ("DEV-P-015", "VYA-POHA-THK-20", "Indori Thick Poha", "88", "kg", 5_600, "20", "kg", ("flattened rice", "thick poha")),
    ("DEV-P-016", "VYA-BESAN-10", "Chana Besan", "65", "kg", 8_900, "10", "kg", ("gram flour", "besan")),
    ("DEV-P-017", "VYA-GHEE-COW-5", "Cow Ghee", "7", "kg", 58_000, "5", "kg", ("ghee",)),
    ("DEV-P-018", "VYA-COFFEE-INS-5", "Instant Coffee", "24", "kg", 92_000, "5", "kg", ("coffee",)),
    ("DEV-P-019", "VYA-BISCUIT-MIX-1", "Assorted Tea Biscuits", "420", "pack", 3_500, "1", "pack", ("tea biscuits", "biscuits")),
    ("DEV-P-020", "VYA-MILK-POW-1", "Full Cream Milk Powder", "36", "kg", 42_000, "1", "kg", ("milk powder",)),
]

SUBSTITUTIONS = [
    ("DEV-P-001", "DEV-P-002", "Shop-approved alternate rice variety when premium basmati is unavailable"),
    ("DEV-P-008", "DEV-P-009", "Shop-approved alternative cooking oil; customer confirmation required"),
]

CUSTOMER_PRICES = [
    ("DEV-C-001", "DEV-P-001", 11_900, "INR"),
    ("DEV-C-004", "DEV-P-004", 12_950, "INR"),
    ("DEV-C-007", "DEV-P-002", 6_950, "INR"),
    ("DEV-C-008", "DEV-P-008", 13_450, "INR"),
]

# Each order record represents past trade history; seeding it does not adjust
# current stock or the separately maintained current credit balance.
HISTORICAL_ORDERS = [
    ("DEV-C-001", "2026-08-14", "delivered", (("DEV-P-001", "50", 11_900), ("DEV-P-004", "25", 13_500))),
    ("DEV-C-001", "2026-09-22", "delivered", (("DEV-P-003", "40", 4_800), ("DEV-P-008", "30", 13_800))),
    ("DEV-C-002", "2026-08-19", "delivered", (("DEV-P-002", "60", 7_200), ("DEV-P-007", "50", 4_450))),
    ("DEV-C-002", "2026-10-02", "confirmed", (("DEV-P-006", "25", 7_400),)),
    ("DEV-C-003", "2026-08-11", "delivered", (("DEV-P-005", "30", 11_800), ("DEV-P-011", "25", 2_100))),
    ("DEV-C-003", "2026-09-28", "delivered", (("DEV-P-001", "20", 12_500),)),
    ("DEV-C-004", "2026-08-25", "delivered", (("DEV-P-004", "100", 12_950), ("DEV-P-009", "45", 15_200))),
    ("DEV-C-004", "2026-10-08", "confirmed", (("DEV-P-010", "10", 28_000), ("DEV-P-012", "5", 18_500))),
    ("DEV-C-005", "2026-08-17", "delivered", (("DEV-P-015", "25", 5_600), ("DEV-P-016", "10", 8_900))),
    ("DEV-C-005", "2026-09-30", "delivered", (("DEV-P-007", "40", 4_450),)),
    ("DEV-C-006", "2026-08-21", "delivered", (("DEV-P-003", "50", 4_800), ("DEV-P-006", "25", 7_400))),
    ("DEV-C-006", "2026-10-06", "confirmed", (("DEV-P-013", "4", 24_000), ("DEV-P-014", "5", 12_500))),
    ("DEV-C-007", "2026-08-12", "delivered", (("DEV-P-002", "80", 6_950), ("DEV-P-010", "15", 28_000))),
    ("DEV-C-007", "2026-09-25", "delivered", (("DEV-P-001", "35", 12_500),)),
    ("DEV-C-008", "2026-08-29", "delivered", (("DEV-P-008", "40", 13_450), ("DEV-P-019", "120", 3_500))),
    ("DEV-C-008", "2026-10-10", "confirmed", (("DEV-P-017", "3", 58_000), ("DEV-P-018", "2", 92_000))),
]

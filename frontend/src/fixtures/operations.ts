/** DEVELOPMENT FIXTURES ONLY - never connect these values to business rules. */
export const dashboardExamples = [
  { label: 'Fixture grocery orders received', value: '12', context: 'Development data only' },
  { label: 'Fixture orders awaiting review', value: '3', context: 'Development data only' },
  { label: 'Fixture customer conversations', value: '8', context: 'Development data only' },
]

export const inventoryExamples = [
  { sku: 'DEV-GROCERY-101', name: 'Basmati Rice, 5 kg', availability: 'Fixture: backend confirmation pending', updatedAt: '26 Oct 2026, 9:15 am' },
  { sku: 'DEV-GROCERY-102', name: 'Whole Wheat Flour, 5 kg', availability: 'Fixture: available', updatedAt: '26 Oct 2026, 9:05 am' },
  { sku: 'DEV-GROCERY-103', name: 'Cooking Oil, 1 L', availability: 'Fixture: unavailable', updatedAt: '25 Oct 2026, 5:30 pm' },
  { sku: 'DEV-GROCERY-104', name: 'Split Red Lentils, 1 kg', availability: 'Fixture: available', updatedAt: '25 Oct 2026, 5:15 pm' },
  { sku: 'DEV-GROCERY-105', name: 'Iodised Salt, 1 kg', availability: 'Fixture: available', updatedAt: '25 Oct 2026, 5:05 pm' },
]

export const customerExamples = [
  { id: 'DEV-CUSTOMER-201', name: 'Development Customer A', contact: 'Fixture contact unavailable', lastOrder: 'DEV-ORDER-1042' },
  { id: 'DEV-CUSTOMER-202', name: 'Development Customer B', contact: 'Fixture contact unavailable', lastOrder: 'DEV-ORDER-1041' },
  { id: 'DEV-CUSTOMER-203', name: 'Development Customer C', contact: 'Fixture contact unavailable', lastOrder: 'DEV-ORDER-1040' },
]

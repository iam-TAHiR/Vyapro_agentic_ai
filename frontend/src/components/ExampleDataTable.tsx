import { useI18n } from '../services/i18n'

type ExampleDataTableProps = {
  caption: string
  columns: string[]
  rows: string[][]
}

export function ExampleDataTable({ caption, columns, rows }: ExampleDataTableProps) {
  const { t } = useI18n()
  return (
    <div className="table-wrap">
      <table>
        <caption>{t(caption)}</caption>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{t(column)}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row[0]}-${index}`}>{row.map((cell, cellIndex) => <td key={`${cell}-${cellIndex}`} data-label={t(columns[cellIndex])}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

type ExampleDataTableProps = {
  caption: string
  columns: string[]
  rows: string[][]
}

export function ExampleDataTable({ caption, columns, rows }: ExampleDataTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <caption>{caption}</caption>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row[0]}-${index}`}>{row.map((cell, cellIndex) => <td key={`${cell}-${cellIndex}`} data-label={columns[cellIndex]}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

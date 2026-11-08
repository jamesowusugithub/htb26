import { isTrace } from '../data/traceMeta'

export function Legend() {
  const trace = isTrace()
  const dots: [string, string][] = trace ? [['#9aa0a6', 'Low (spot)'], ['#f08a24', 'High']] : [
    ['#9aa0a6', 'Low'], ['#3f7fe0', 'Medium'], ['#f08a24', 'High'], ['#f5c518', 'VIP (crown)'],
  ]
  return (
    <ul className="legend" aria-label="How to read the restaurant">
      {dots.map(([c, n]) => (
        <li key={n}><i style={{ background: c }} aria-hidden />{n} priority</li>
      ))}
      <li>{trace ? 'Bigger group = more GPUs requested (tag shows the count)' : 'Bigger group = more GPU memory (GB tag)'}</li>
      {trace && <li>Bar over a waiting party = how long they have waited (green under 24 min, red over 30; a display scale)</li>}
      <li>Steam = hot chef. Closed sign = GPU switched off</li>
      <li>Thermometer next to each chef = temperature ({trace ? 'proxy from measured H100 data' : 'simulated'})</li>
    </ul>
  )
}

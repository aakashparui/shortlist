import { Link, useLocation } from 'react-router-dom'

import { PageHeader, Panel } from '../components/ui'

export function NotFoundPage() {
  const location = useLocation()
  return (
    <div className="page">
      <PageHeader
        eyebrow="Not found"
        title="No such view"
        lede={`There is nothing at ${location.pathname}.`}
      />
      <Panel title="Where to go instead">
        <div className="col-tight">
          <Link to="/">Control room</Link>
          <Link to="/payments">Payment search</Link>
          <Link to="/payments/new">Payment simulator</Link>
          <Link to="/qa/scenarios">Scenario library</Link>
          <Link to="/system/configuration">Configuration</Link>
        </div>
      </Panel>
    </div>
  )
}

/** Root React component.
 *
 * App deliberately contains no feature logic. It selects the page to render,
 * while the inspection feature owns its state, API calls, and presentation.
 */

import './App.css'
import { ConnectorInspectionPage } from './features/inspection/ConnectorInspectionPage'


function App() {
  return <ConnectorInspectionPage />
}


export default App

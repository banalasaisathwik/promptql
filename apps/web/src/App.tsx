/** Root React component.
 *
 * App deliberately contains no feature logic. It selects the page to render,
 * while the readiness feature owns its state, API calls, and presentation.
 */

import './App.css'
import { MergeReadinessPage } from './features/inspection/MergeReadinessPage'


function App() {
  return <MergeReadinessPage />
}


export default App

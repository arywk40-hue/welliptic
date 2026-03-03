/**
 * deploy_applets.mjs — Deploy LexAudit WASM applets to Weilchain
 * Matches the SDK example.js deploy pattern exactly.
 * Usage:  node scripts/deploy_applets.mjs
 */
import fs from 'fs/promises'
import { WeilWallet } from '@weilliptic/weil-sdk'

const SENTINEL = 'https://sentinel.unweil.me'

async function fileToHex(filePath) {
  const buffer = await fs.readFile(filePath)
  return buffer.toString('hex')
}

async function main() {
  const privateKey = (await fs.readFile('private_key.wc', 'utf-8')).trim()
  console.log('Wallet loaded')

  const wallet = new WeilWallet({ privateKey, sentinelEndpoint: SENTINEL })

  // List pods — deploy to first non-SENATE pod (like SDK example)
  const pods = await wallet.pods.list()
  console.log('Found ' + pods.length + ' pod(s):', pods.map(p => p.podId))

  const targetPod = pods.find(p => p.podId !== 'SENATE')?.podId || pods[0]?.podId
  console.log('Deploying to pod: ' + targetPod + '\n')

  // --- ClauseExtractor ---
  console.log('Deploying ClauseExtractor...')
  const [clauseBody, clauseWidl] = await Promise.all([
    fileToHex('src/applets/wasm/clause_extractor.wasm'),
    fileToHex('src/applets/clause_extractor.widl'),
  ])

  const clauseResult = await wallet.contracts.deploy(clauseBody, clauseWidl, {
    name: 'lexaudit-clause-extractor',
    pods: targetPod,
  })
  console.log('ClauseExtractor result:', JSON.stringify(clauseResult, null, 2))

  // --- RiskScorer ---
  console.log('\nDeploying RiskScorer...')
  const [riskBody, riskWidl] = await Promise.all([
    fileToHex('src/applets/wasm/risk_scorer.wasm'),
    fileToHex('src/applets/risk_scorer.widl'),
  ])

  const riskResult = await wallet.contracts.deploy(riskBody, riskWidl, {
    name: 'lexaudit-risk-scorer',
    pods: targetPod,
  })
  console.log('RiskScorer result:', JSON.stringify(riskResult, null, 2))

  // --- Extract addresses ---
  const clauseAddr = clauseResult?.contract_address || clauseResult
  const riskAddr = riskResult?.contract_address || riskResult

  console.log('\n' + '='.repeat(60))
  console.log('Add these to your .env file:')
  console.log('='.repeat(60))
  console.log('CLAUSE_EXTRACTOR_APPLET_ID=' + clauseAddr)
  console.log('RISK_SCORER_APPLET_ID=' + riskAddr)
  console.log('='.repeat(60))
}

main().catch(err => {
  console.error('Deploy failed:', err)
  process.exit(1)
})

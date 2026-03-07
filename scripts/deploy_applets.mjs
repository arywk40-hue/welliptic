/**
 * deploy_applets.mjs — Deploy LexAudit WASM applets to Weilchain
 * Matches the SDK example.js deploy pattern exactly.
 * Usage:  node scripts/deploy_applets.mjs [--pod <pod_id>]
 *
 * Pod selection (per hackathon announcement 2026-03-07):
 *   - Prefer asia-south pod if in the region (pass --pod asia-south)
 *   - NEVER deploy to SENATE pods
 *   - Falls back to first non-SENATE pod if no --pod flag given
 *
 * Model (per hackathon announcement 2026-03-07):
 *   - Use gpt-4o / gpt-5 with the free OpenAI key provided
 */
import fs from 'fs/promises'
import { WeilWallet } from '@weilliptic/weil-sdk'

const SENTINEL = 'https://sentinel.unweil.me'

// Allow --pod <id> CLI override (e.g. node deploy_applets.mjs --pod asia-south)
const podArgIdx = process.argv.indexOf('--pod')
const POD_OVERRIDE = podArgIdx !== -1 ? process.argv[podArgIdx + 1] : null

async function fileToHex(filePath) {
  const buffer = await fs.readFile(filePath)
  return buffer.toString('hex')
}

async function main() {
  const privateKey = (await fs.readFile('private_key.wc', 'utf-8')).trim()
  console.log('Wallet loaded')

  const wallet = new WeilWallet({ privateKey, sentinelEndpoint: SENTINEL })

  // List pods — prefer asia-south, NEVER deploy to SENATE (per hackathon rules)
  const pods = await wallet.pods.list()
  console.log('Found ' + pods.length + ' pod(s):', pods.map(p => p.podId))

  let targetPod
  if (POD_OVERRIDE) {
    targetPod = POD_OVERRIDE
    console.log('Using --pod override: ' + targetPod)
  } else {
    // Priority: asia-south → any non-SENATE pod
    const SENATE_PATTERN = /^SENATE/i
    targetPod =
      pods.find(p => p.podId === 'asia-south')?.podId ||
      pods.find(p => !SENATE_PATTERN.test(p.podId))?.podId ||
      pods[0]?.podId
  }
  console.log('Deploying to pod: ' + targetPod + '\n')
  if (/^SENATE/i.test(targetPod || '')) {
    console.error('❌ Target pod is a SENATE pod — aborting. Use --pod <pod_id> to specify a valid pod.')
    process.exit(1)
  }

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

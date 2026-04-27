# INCA - Insurance Claims Bot Architecture & Analysis

## Project Overview

INCA is an automated insurance claims processing and validation system designed to handle German auto insurance claims (KFZ insurance) with sophisticated fraud detection, multi-partner integrations, and compliance-aware decision making.

## Documents Received

### 1. Policy Information Checklist (`Policy-Info.md`)
A comprehensive checklist of all insurance policy data required for claims validation, including:
- **Policy Contract Data**: Policy number, product, tariff, effective dates, premium status
- **Vehicle Information**: VIN, license plate, usage type, mileage band, modifications
- **Coverage Details**: Liability limits, Kasko types, deductibles, add-ons, no-claims class
- **Driver Scope**: Named drivers, age restrictions, license dates
- **Geographic/Temporal Scope**: Country coverage, seasonal plates, policy transfer conditions
- **Exclusions**: Race exclusions, negligence clauses, telematics conditions
- **Insurer Database**: Customer master data, claims history, fraud flags, HIS (Hinweis- und Informationssystem) records

## Architecture Overview

### Core Processing Pipeline (6 Stages)

```
1. Claim Intake & Validation
   └─ OCR parsing, deduplication, structured data extraction

2. Policy Coverage Determination
   └─ Rules engine checks policy applicability, exclusions, deductibles

3. Driver & Vehicle Validation
   └─ Verify declared vs. actual driver/vehicle, damage history

4. Risk & Fraud Assessment
   └─ Multi-source fraud scoring (telematics, HIS, OEM data, narrative)

5. Disclosure & Communication
   └─ Multi-channel delivery (email, SMS, WhatsApp) with regulatory compliance

6. Resolution & Payout
   └─ Repair authorization, payment processing, settlement
```

### Data Layers

| Layer | Contents | Purpose |
|-------|----------|---------|
| **Layer 1: Policy Management** | Policy docs, tariffs, AKB | Source of truth for coverage rules |
| **Layer 2: Customer CDP** | Policyholder, drivers, preferences | Identity & consent management |
| **Layer 3: Vehicle Registry** | VIN, registration, telematics | Vehicle data & mileage tracking |
| **Layer 4: Claims History** | Prior claims, HIS, SIU flags | Fraud detection & context |

## Partner Ecosystem (10 Integration Points)

### Phase 1 (Months 3-4): Intake & Communication
- **Document.ai / ABBYY** - OCR for claim form parsing
- **Twilio / SendGrid** - Email, SMS, WhatsApp delivery
- **Salesforce / Custom** - Customer portal & self-service

### Phase 2 (Months 5-6): Fraud Prevention
- **Geotab / Verizon Connect** - Real-time telematics (trip data, events)
- **LexisNexis HIS** - Fraud pattern detection, SIU routing
- **CarVertical / HPI Check** - Vehicle damage history, market value

### Phase 3 (Months 7-9): High-Value Claims
- **BMW ConnectedDrive / Mercedes / VW** - Airbag, braking, GPS event data
- **ADAC / Bosch Service** - Repair network, work authorization
- **Internal ML** - Advanced fraud scoring

### Phase 4 (Months 10-12): Scale & Settlement
- **Stripe / SEPA** - Payment processing & payouts
- **Custom Chatbot** - Portal enhancement, Q&A automation
- **LawGeek / Compliance Tools** - Auto-generated disclosure, audit trail

## Decision Logic: Risk Assessment & Fraud Scoring

### Fraud Score Calculation
- **HIS Check**: +0 to +100 points (pattern match, known fraudster)
- **Claim Frequency**: +0 to +50 points (multiple claims, location clustering)
- **Telematics Match**: +0 to +100 points (narrative vs. device data)
- **OEM Event Match**: +0 to +75 points (airbag/braking consistency)
- **Narrative Plausibility**: +0 to +50 points (damage severity vs. impact)

### Decision Gates
| Score | Decision | Action |
|-------|----------|--------|
| **0-25** | Auto-Approve | Immediate coverage + disclosure |
| **26-60** | Manual Review | Human adjuster (5-15 min) |
| **61-100** | SIU Escalation | Investigation handler (5-10 days) |
| **>100** | Fraud Denial | HIS notification, appeal rights |

## Implementation Roadmap (12 Months)

### Month 1-2: Foundation & MVP
- Core rules engine (policy lookup, coverage determination)
- Claim data model & schema
- Audit logging infrastructure
- Compliance framework (VVG, GDPR)

### Month 3-4: Phase 1 Integrations
- OCR provider (50% auto-extract rate)
- Email/SMS platform (80% same-day delivery)
- Customer portal (real-time status tracking)
- **Target**: 50% auto-approval rate, <5min decision time

### Month 5-6: Phase 2 Integrations
- Telematics provider (real-time validation)
- HIS/Fraud network (automated lookups)
- Vehicle data provider (damage history)
- **Target**: 30% auto-approval → 50%, <2s decision time

### Month 7-9: Phase 3 Integrations
- Connected-car OEM data (airbag/braking validation)
- Repair networks (work authorization)
- Advanced ML fraud scoring
- **Target**: 50% auto-approval, +40% fraud detection precision

### Month 10-12: Phase 4 (Scale)
- Payment integration (automated payouts)
- Chatbot/portal enhancements
- Compliance automation
- **Target**: 60%+ auto-approval, <24h claim-to-decision, 95% satisfaction

## Key Performance Indicators (Year 1 Targets)

### Operational
- Claims processed: 10,000
- Auto-approval rate: 60%
- Average decision time: 5 minutes
- Manual review rate: 30%
- SIU escalation rate: 10%

### Financial
- Fraud prevention savings: €500K
- Cost per claim: €12
- Processing cost reduction: 40% vs. manual

### Customer Experience
- NPS score: 65+
- First contact resolution: 70%
- Satisfaction rating: 80%
- Disclosure clarity: 4.2/5

### Compliance
- Regulatory findings: 0
- GDPR incidents: 0
- Disclosure accuracy: 98%+
- Audit trail completeness: 100%

## Technical Stack

### Backend
- API Gateway (Kong / AWS API Gateway)
- Message Queue (RabbitMQ / Kafka)
- Cache Layer (Redis)
- Circuit Breaker Pattern (partner failover)

### Data Pipeline
- ETL Orchestration (Airflow / Prefect)
- Data Warehouse (Snowflake / BigQuery)
- Event Streaming (Kafka Connect)

### Security & Compliance
- API Key Vault (HashiCorp Vault)
- TLS 1.3 for all partner APIs
- AES-256 encryption at rest
- Immutable audit logging

## Partner ROI & Integration Timeline

| Partner | Impl. Cost | Monthly Cost | Fraud Lift | Time Savings | Payback |
|---------|-----------|--------------|-----------|-------------|---------|
| Telematics | €15K | €500 | +35% | 20% faster | 4-6 mo |
| Vehicle Data | €8K | €600 | +15% | 10% faster | 3-4 mo |
| HIS/Fraud | €25K | €400 | +50% | 15% faster | 6-8 mo |
| OEM Events | €30K | €300 | +25% | 5% faster | 8-10 mo |
| Twilio | €5K | €200 | N/A | 30% faster | 2-3 mo |

## Next Steps

### Immediate (Week 1)
- [ ] Validate architecture with target insurer
- [ ] Confirm partner priorities (which 2-3 to start with)
- [ ] Define MVP scope (claim types, coverage limits)

### Short-term (Month 1)
- [ ] Build core rules engine
- [ ] Design claim data model
- [ ] Set up audit logging
- [ ] Establish compliance framework

### Medium-term (Months 2-3)
- [ ] Integrate Phase 1 partners
- [ ] Build customer portal
- [ ] Conduct UAT
- [ ] Prepare production launch

## Questions for Stakeholders

1. **Claim Types**: Which to prioritize? (collision, theft, liability, comprehensive?)
2. **Target Insurers**: Size, geography, German-specific requirements?
3. **Build vs. Partner**: Build integrations (expensive/flexible) or buy (faster/limited)?
4. **Fraud Tolerance**: False positive tolerance vs. false negative reduction?
5. **Decision Transparency**: How much explanation needed for auto-decisions?
6. **Timeline**: MVP in 2, 6, or 12 months?

---

## Appendix: Visual Diagrams

Five FigJam architecture diagrams have been created:

1. **Claims Processing Pipeline** - End-to-end flow with all partner touchpoints
2. **Partner Ecosystem & Data Architecture** - Core engine, data layers, partners, external systems
3. **Risk Assessment Decision Tree** - Fraud scoring and claim routing logic
4. **12-Month Implementation Roadmap** - Timeline across 5 phases
5. **Partner Integration Matrix** - Which partners at each processing stage

All diagrams are available in FigJam for interactive exploration and annotation.

---

**Document Version**: 1.0
**Created**: April 25, 2026
**Author**: Claude Code
**Status**: Ready for stakeholder review

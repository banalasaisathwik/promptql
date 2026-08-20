from app.investigations import (
    CommitAssociatedWithPullRequestFact,
    CommitEvidenceContent,
    DeploymentEvidenceContent,
    DeploymentReferencesCommitFact,
    Evidence,
    PullRequestEvidenceContent,
)
from app.investigations.fact_derivation._ids import fact_id, references


def derive_deployment_code_facts(
    evidence: tuple[Evidence, ...],
) -> tuple[DeploymentReferencesCommitFact | CommitAssociatedWithPullRequestFact, ...]:
    # These are exact Git identities. In particular, equality to a PR head or
    # merge SHA establishes association, not that the PR caused the incident.
    facts: list[DeploymentReferencesCommitFact | CommitAssociatedWithPullRequestFact] = []
    deployments = [item for item in evidence if isinstance(item.content, DeploymentEvidenceContent)]
    commits = [item for item in evidence if isinstance(item.content, CommitEvidenceContent)]
    pull_requests = [item for item in evidence if isinstance(item.content, PullRequestEvidenceContent)]
    for deployment in deployments:
        for commit in commits:
            if deployment.content.commit_sha.lower() != commit.content.commit_sha.lower():
                continue
            facts.append(
                DeploymentReferencesCommitFact(
                    fact_id=fact_id("deployment-references-commit", deployment, commit),
                    evidence_reference_ids=references(deployment, commit),
                    deployment_reference=deployment.content.deployment_reference,
                    commit_sha=commit.content.commit_sha,
                )
            )
            for pull_request in pull_requests:
                pull_content = pull_request.content
                associated_shas = {pull_content.head_sha.lower()}
                if pull_content.merge_commit_sha is not None:
                    associated_shas.add(pull_content.merge_commit_sha.lower())
                if commit.content.commit_sha.lower() not in associated_shas:
                    continue
                facts.append(
                    CommitAssociatedWithPullRequestFact(
                        fact_id=fact_id("commit-associated-with-pull-request", commit, pull_request),
                        evidence_reference_ids=references(commit, pull_request),
                        commit_sha=commit.content.commit_sha,
                        pull_request_number=pull_content.pull_request_number,
                    )
                )
    return tuple(facts)

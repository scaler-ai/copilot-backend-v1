"""
Sales Analysis Service with LLM Integration

This service analyzes sales performance data and conversation transcripts to:
- Infer sales skills from activities and conversations
- Generate constructive feedback on sales conversations
- Identify strengths and improvement areas
- Provide learning recommendations
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException
from sqlmodel import Session, select, func
from app.models import (
    User,
    ScalerCRMAuth,
    ScalerLead,
    ScalerActivity,
    ScalerConversation,
    SalesPerformanceAnalysis,
    SalesSkillRating,
    ConversationFeedback
)
from app.services.llm_service import llm_service
from app.services.llm_prompts import (
    SALES_SKILL_ANALYSIS_PROMPT,
    CONVERSATION_ANALYSIS_PROMPT,
    SALES_FEEDBACK_GENERATION_PROMPT
)

logger = logging.getLogger(__name__)


def parse_datetime(date_string: str) -> datetime:
    """Parse datetime string handling both ISO format and Z suffix"""
    if not date_string:
        return datetime.utcnow()
    
    # Handle Z suffix (Zulu time/UTC)
    if date_string.endswith('Z'):
        date_string = date_string[:-1] + '+00:00'
    
    try:
        return datetime.fromisoformat(date_string)
    except ValueError:
        # Fallback: try parsing with strptime
        try:
            return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f')
        except ValueError:
            try:
                return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                logger.warning(f"Could not parse datetime: {date_string}, using current time")
                return datetime.utcnow()


class SalesAnalysisService:
    """Service for analyzing sales performance and generating insights"""
    
    # Sales skill categories and mappings
    SALES_SKILLS = {
        "communication": {
            "id": "sales_communication",
            "name": "Sales Communication",
            "description": "Ability to communicate effectively with prospects and customers"
        },
        "relationship_building": {
            "id": "sales_relationship",
            "name": "Relationship Building",
            "description": "Building rapport and trust with customers"
        },
        "discovery": {
            "id": "sales_discovery",
            "name": "Discovery & Needs Analysis",
            "description": "Uncovering customer needs and pain points"
        },
        "presentation": {
            "id": "sales_presentation",
            "name": "Product Presentation",
            "description": "Presenting solutions effectively"
        },
        "objection_handling": {
            "id": "sales_objection",
            "name": "Objection Handling",
            "description": "Addressing customer concerns professionally"
        },
        "closing": {
            "id": "sales_closing",
            "name": "Closing Skills",
            "description": "Converting opportunities into deals"
        },
        "time_management": {
            "id": "sales_time_mgmt",
            "name": "Time Management",
            "description": "Efficient use of time and prioritization"
        },
        "follow_up": {
            "id": "sales_follow_up",
            "name": "Follow-up & Persistence",
            "description": "Consistent and timely follow-up"
        }
    }
    
    async def analyze_sales_performance(
        self,
        session: Session,
        user: User,
        crm_auth: ScalerCRMAuth,
        period_months: int = 3
    ) -> SalesPerformanceAnalysis:
        """Analyze overall sales performance and generate skill ratings"""
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=period_months * 30)
            
            # Get performance metrics
            metrics = await self._calculate_performance_metrics(
                session, crm_auth, start_date, end_date
            )
            
            # Get activities for analysis
            activities = session.exec(
                select(ScalerActivity).where(
                    ScalerActivity.crm_auth_id == crm_auth.id,
                    ScalerActivity.activity_date >= start_date.isoformat(),
                    ScalerActivity.activity_date <= end_date.isoformat()
                )
            ).all()
            
            # Prepare data for LLM analysis
            activity_summary = self._prepare_activity_summary(activities)
            
            # Generate LLM analysis
            llm_analysis = await self._generate_performance_analysis(
                session, user, metrics, activity_summary
            )
            
            # Create performance analysis record
            analysis = SalesPerformanceAnalysis(
                analysis_period_start=start_date.isoformat(),
                analysis_period_end=end_date.isoformat(),
                total_leads=metrics["total_leads"],
                total_activities=metrics["total_activities"],
                total_conversations=metrics["total_conversations"],
                conversion_rate=metrics["conversion_rate"],
                average_response_time_hours=metrics.get("average_response_time_hours"),
                activity_breakdown=metrics["activity_breakdown"],
                lead_stage_distribution=metrics["lead_stage_distribution"],
                performance_summary=llm_analysis["summary"],
                strengths_identified=llm_analysis.get("behavioral_strengths", llm_analysis.get("strengths", [])),
                improvement_areas=llm_analysis.get("improvement_opportunities", llm_analysis.get("improvements", [])),
                crm_auth_id=crm_auth.id
            )
            session.add(analysis)
            session.commit()
            
            # Generate skill ratings
            skill_ratings = await self._generate_skill_ratings(
                session, user, analysis, metrics, activity_summary, llm_analysis
            )
            
            # Refresh analysis to include skill ratings
            session.refresh(analysis)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Sales performance analysis failed: {str(e)}")
            raise
    
    async def analyze_conversation(
        self,
        session: Session,
        conversation: ScalerConversation
    ) -> List[ConversationFeedback]:
        """Analyze a sales conversation and generate feedback"""
        try:
            if not conversation.transcript_text:
                logger.warning(f"No transcript available for conversation {conversation.conversation_id}")
                return []
            
            # Get lead information if available
            lead_info = None
            if conversation.lead_id:
                lead = session.get(ScalerLead, conversation.lead_id)
                if lead:
                    lead_info = {
                        "name": lead.lead_name,
                        "company": lead.company,
                        "stage": lead.lead_stage,
                        "status": lead.lead_status
                    }
            
            # Get user from CRM auth
            crm_auth = session.get(ScalerCRMAuth, conversation.crm_auth_id)
            if not crm_auth:
                logger.error(f"No CRM auth found for conversation {conversation.id}")
                return []
            
            user = session.get(User, crm_auth.owner_id)
            if not user:
                logger.error(f"No user found for CRM auth {crm_auth.id}")
                return []
            
            # Analyze conversation with LLM
            analysis = await self._analyze_conversation_transcript(
                session,
                user,
                conversation.transcript_text,
                conversation.conversation_type,
                lead_info
            )
            
            # Create feedback items
            feedback_items = []
            for feedback_data in analysis["feedback_items"]:
                feedback = ConversationFeedback(
                    feedback_type=feedback_data["type"],
                    feedback_category=feedback_data["category"],
                    feedback_text=feedback_data["text"],
                    specific_moment=feedback_data.get("moment"),
                    suggested_response=feedback_data.get("suggestion"),
                    impact_level=feedback_data.get("impact", "medium"),
                    confidence_score=feedback_data.get("confidence", 80),
                    conversation_id=conversation.id
                )
                session.add(feedback)
                feedback_items.append(feedback)
            
            # Update conversation analysis status
            conversation.analysis_status = "completed"
            conversation.analyzed_at = datetime.utcnow().isoformat()
            if analysis.get("summary"):
                conversation.transcript_summary = analysis["summary"]
            session.add(conversation)
            
            session.commit()
            return feedback_items
            
        except Exception as e:
            logger.error(f"Conversation analysis failed: {str(e)}")
            conversation.analysis_status = "failed"
            session.add(conversation)
            session.commit()
            return []
    
    async def _calculate_performance_metrics(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Calculate detailed performance metrics"""
        # Get all relevant data
        leads = session.exec(
            select(ScalerLead).where(
                ScalerLead.crm_auth_id == crm_auth.id,
                ScalerLead.created_date >= start_date.isoformat(),
                ScalerLead.created_date <= end_date.isoformat()
            )
        ).all()
        
        activities = session.exec(
            select(ScalerActivity).where(
                ScalerActivity.crm_auth_id == crm_auth.id,
                ScalerActivity.activity_date >= start_date.isoformat(),
                ScalerActivity.activity_date <= end_date.isoformat()
            )
        ).all()
        
        conversations = session.exec(
            select(ScalerConversation).where(
                ScalerConversation.crm_auth_id == crm_auth.id,
                ScalerConversation.conversation_date >= start_date.isoformat(),
                ScalerConversation.conversation_date <= end_date.isoformat()
            )
        ).all()
        
        # Calculate conversion metrics
        total_leads = len(leads)
        converted_leads = len([l for l in leads if l.lead_status in ["converted", "closed-won"]])
        conversion_rate = (converted_leads / total_leads * 100) if total_leads > 0 else 0
        
        # Activity analysis
        activity_breakdown = {}
        total_duration = 0
        engagement_scores = []
        
        for activity in activities:
            # Count by type
            activity_breakdown[activity.activity_type] = activity_breakdown.get(activity.activity_type, 0) + 1
            
            # Track duration
            if activity.duration_minutes:
                total_duration += activity.duration_minutes
            
            # Track engagement
            if activity.engagement_score:
                engagement_scores.append(activity.engagement_score)
        
        # Lead stage analysis
        stage_distribution = {}
        for lead in leads:
            if lead.lead_stage:
                stage_distribution[lead.lead_stage] = stage_distribution.get(lead.lead_stage, 0) + 1
        
        # Response time calculation (simplified)
        response_times = []
        for i, activity in enumerate(activities):
            if i > 0 and activity.lead_id == activities[i-1].lead_id:
                # Calculate time between activities on same lead
                prev_date = parse_datetime(activities[i-1].activity_date)
                curr_date = parse_datetime(activity.activity_date)
                hours_diff = abs((curr_date - prev_date).total_seconds() / 3600)
                if hours_diff < 168:  # Within a week
                    response_times.append(hours_diff)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else None
        avg_engagement = sum(engagement_scores) / len(engagement_scores) if engagement_scores else None
        
        return {
            "total_leads": total_leads,
            "converted_leads": converted_leads,
            "total_activities": len(activities),
            "total_conversations": len(conversations),
            "conversion_rate": round(conversion_rate, 2),
            "average_response_time_hours": round(max(0, avg_response_time), 2) if avg_response_time else None,
            "average_engagement_score": round(avg_engagement, 2) if avg_engagement else None,
            "total_activity_duration_hours": round(total_duration / 60, 2),
            "activity_breakdown": activity_breakdown,
            "lead_stage_distribution": stage_distribution,
            "conversations_with_transcripts": len([c for c in conversations if c.transcript_available])
        }
    
    def _prepare_activity_summary(self, activities: List[ScalerActivity]) -> Dict[str, Any]:
        """Prepare detailed activity data for LLM analysis with behavioral insights"""
        summary = {
            "total_activities": len(activities),
            "activity_types": {},
            "outcomes": {},
            "timing_patterns": {},
            "follow_up_analysis": {},
            "engagement_patterns": {},
            "behavioral_insights": []
        }
        
        # Group activities by lead for sequence analysis
        lead_activities = {}
        for activity in activities:
            lead_id = activity.lead_id
            if lead_id not in lead_activities:
                lead_activities[lead_id] = []
            lead_activities[lead_id].append(activity)
        
        # Analyze activity patterns
        follow_up_gaps = []
        activity_sequences = []
        
        for lead_id, lead_acts in lead_activities.items():
            # Sort by date for sequence analysis
            sorted_acts = sorted(lead_acts, key=lambda x: parse_datetime(x.activity_date))
            
            # Analyze follow-up timing
            for i in range(len(sorted_acts) - 1):
                current = parse_datetime(sorted_acts[i].activity_date)
                next_act = parse_datetime(sorted_acts[i + 1].activity_date)
                gap_hours = (next_act - current).total_seconds() / 3600
                if gap_hours > 0:
                    follow_up_gaps.append(gap_hours)
            
            # Capture activity sequences
            if len(sorted_acts) >= 2:
                sequence = " → ".join([act.activity_type or "unknown" for act in sorted_acts[:3]])
                activity_sequences.append(sequence)
        
        # Count activity types and outcomes
        for activity in activities:
            activity_type = activity.activity_type or "unknown"
            outcome = activity.outcome or "not_specified"
            
            summary["activity_types"][activity_type] = summary["activity_types"].get(activity_type, 0) + 1
            summary["outcomes"][outcome] = summary["outcomes"].get(outcome, 0) + 1
            
            # Analyze timing patterns (hour of day)
            try:
                activity_time = parse_datetime(activity.activity_date)
                hour = activity_time.hour
                time_period = "morning" if 6 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening"
                summary["timing_patterns"][time_period] = summary["timing_patterns"].get(time_period, 0) + 1
            except:
                pass
        
        # Calculate follow-up insights
        if follow_up_gaps:
            avg_gap = sum(follow_up_gaps) / len(follow_up_gaps)
            summary["follow_up_analysis"] = {
                "average_follow_up_time_hours": round(avg_gap, 1),
                "total_follow_ups": len(follow_up_gaps),
                "quick_follow_ups": len([gap for gap in follow_up_gaps if gap <= 24]),
                "delayed_follow_ups": len([gap for gap in follow_up_gaps if gap > 72])
            }
        
        # Find common activity sequences
        if activity_sequences:
            from collections import Counter
            sequence_counts = Counter(activity_sequences)
            summary["common_sequences"] = dict(sequence_counts.most_common(3))
        
        # Generate behavioral insights
        insights = []
        
        # Activity volume insights
        activities_per_lead = len(activities) / len(lead_activities) if lead_activities else 0
        if activities_per_lead > 5:
            insights.append(f"High engagement: averages {activities_per_lead:.1f} activities per lead")
        elif activities_per_lead < 2:
            insights.append(f"Low engagement: only {activities_per_lead:.1f} activities per lead on average")
        
        # Follow-up timing insights
        if follow_up_gaps:
            quick_follow_ups = len([gap for gap in follow_up_gaps if gap <= 24])
            follow_up_rate = (quick_follow_ups / len(follow_up_gaps)) * 100
            if follow_up_rate > 70:
                insights.append(f"Excellent follow-up timing: {follow_up_rate:.0f}% of follow-ups within 24 hours")
            elif follow_up_rate < 30:
                insights.append(f"Slow follow-up timing: only {follow_up_rate:.0f}% of follow-ups within 24 hours")
        
        # Activity mix insights
        if summary["activity_types"]:
            most_common = max(summary["activity_types"], key=summary["activity_types"].get)
            most_common_pct = (summary["activity_types"][most_common] / len(activities)) * 100
            insights.append(f"Primary activity: {most_common} ({most_common_pct:.0f}% of all activities)")
            
            # Check for activity diversity
            if len(summary["activity_types"]) == 1:
                insights.append("Limited activity variety - only using one type of outreach")
            elif len(summary["activity_types"]) >= 4:
                insights.append("Good activity diversity - using multiple outreach channels")
        
        summary["behavioral_insights"] = insights
        
        return summary
    
    async def _generate_performance_analysis(
        self,
        session: Session,
        user: User,
        metrics: Dict[str, Any],
        activity_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate performance analysis using LLM"""
        prompt = f"""
        You are an expert sales coach analyzing a sales representative's performance. Provide specific, actionable insights based on their actual behavior patterns.

        PERFORMANCE DATA:
        - Total Leads Handled: {metrics['total_leads']}
        - Total Activities Completed: {metrics['total_activities']}
        - Conversion Rate: {metrics['conversion_rate']}%
        - Average Response Time: {metrics.get('average_response_time_hours', 'N/A')} hours
        - Average Engagement Score: {metrics.get('average_engagement_score', 'N/A')}/10
        - Activity Mix: {json.dumps(metrics['activity_breakdown'], indent=2)}
        - Lead Pipeline: {json.dumps(metrics['lead_stage_distribution'], indent=2)}

        BEHAVIORAL PATTERNS:
        {json.dumps(activity_summary, indent=2)}

        ANALYSIS FRAMEWORK:
        Focus on identifying specific behavioral patterns and providing actionable recommendations.

        Provide detailed analysis in JSON format:
        {{
            "summary": "2-3 sentence performance overview focusing on key behavioral insights",
            "behavioral_strengths": [
                "Specific positive behaviors observed with evidence from data"
            ],
            "improvement_opportunities": [
                {{
                    "area": "Specific area needing improvement",
                    "current_behavior": "What they're doing now (with data evidence)",
                    "recommended_action": "Specific action they should take",
                    "expected_impact": "How this will improve their results",
                    "implementation_tip": "Practical tip for implementing this change"
                }}
            ],
            "success_patterns": [
                "Patterns that correlate with better outcomes"
            ],
            "time_management_insights": [
                "Specific insights about their time allocation and efficiency"
            ],
            "next_30_days_action_plan": [
                {{
                    "week": 1,
                    "focus_area": "Primary area to focus on",
                    "specific_actions": ["Action 1", "Action 2"],
                    "success_metrics": "How to measure progress"
                }}
            ],
            "performance_rating": {{
                "overall_score": 7,
                "explanation": "Why this score based on data",
                "potential_ceiling": "What score they could reach with improvements"
            }}
        }}
        """
        
        try:
            response = await llm_service.generate_response(user, session, [{"role": "user", "content": prompt}], temperature=0.3)
            
            # Parse JSON response - check if it's already a dict or needs parsing
            if isinstance(response, dict):
                analysis = response.get('content', response)
                if isinstance(analysis, str):
                    analysis = json.loads(analysis)
            else:
                analysis = json.loads(response)
            
            # Ensure required fields and provide enhanced insights
            return {
                "summary": analysis.get("summary", "Performance analysis completed."),
                "behavioral_strengths": analysis.get("behavioral_strengths", []),
                "improvement_opportunities": analysis.get("improvement_opportunities", []),
                "success_patterns": analysis.get("success_patterns", []),
                "time_management_insights": analysis.get("time_management_insights", []),
                "next_30_days_action_plan": analysis.get("next_30_days_action_plan", []),
                "performance_rating": analysis.get("performance_rating", {
                    "overall_score": 5,
                    "explanation": "Unable to generate detailed rating",
                    "potential_ceiling": "8"
                }),
                # Keep legacy fields for backward compatibility
                "strengths": analysis.get("behavioral_strengths", []),
                "improvements": [opp.get("area", "General improvement") for opp in analysis.get("improvement_opportunities", [])],
                "rating": analysis.get("performance_rating", {}).get("overall_score", 5)
            }
            
        except Exception as e:
            logger.error(f"LLM analysis failed: {str(e)}")
            return {
                "summary": "Unable to generate detailed analysis at this time.",
                "strengths": ["Consistent activity levels"],
                "improvements": ["Increase conversion rate"],
                "rating": 5
            }
    
    async def _generate_skill_ratings(
        self,
        session: Session,
        user: User,
        analysis: SalesPerformanceAnalysis,
        metrics: Dict[str, Any],
        activity_summary: Dict[str, Any],
        llm_analysis: Dict[str, Any]
    ) -> List[SalesSkillRating]:
        """Generate skill ratings based on performance data"""
        skill_ratings = []
        
        # Analyze each skill category
        for skill_key, skill_info in self.SALES_SKILLS.items():
            # Calculate skill-specific metrics
            skill_evidence = self._gather_skill_evidence(
                skill_key, metrics, activity_summary, llm_analysis
            )
            
            # Generate skill rating with LLM
            rating_data = await self._rate_skill(
                session, user, skill_info, skill_evidence, metrics
            )
            
            # Create skill rating record
            skill_rating = SalesSkillRating(
                skill_id=skill_info["id"],
                skill_name=skill_info["name"],
                skill_category=skill_key,
                inferred_level=rating_data["level"],
                confidence_score=rating_data["confidence"],
                evidence_summary=rating_data["evidence"],
                evidence_count=rating_data["evidence_count"],
                improvement_suggestions=rating_data.get("suggestions"),
                analysis_id=analysis.id
            )
            session.add(skill_rating)
            skill_ratings.append(skill_rating)
        
        session.commit()
        return skill_ratings
    
    def _gather_skill_evidence(
        self,
        skill_key: str,
        metrics: Dict[str, Any],
        activity_summary: Dict[str, Any],
        llm_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gather evidence for specific skill assessment"""
        evidence = {
            "metrics": {},
            "activities": [],
            "strengths": [],
            "improvements": []
        }
        
        # Map metrics to skills
        if skill_key == "communication":
            evidence["metrics"]["email_count"] = metrics["activity_breakdown"].get("email", 0)
            evidence["metrics"]["call_count"] = metrics["activity_breakdown"].get("call", 0)
            evidence["metrics"]["engagement_score"] = metrics.get("average_engagement_score")
            
        elif skill_key == "closing":
            evidence["metrics"]["conversion_rate"] = metrics["conversion_rate"]
            evidence["metrics"]["converted_leads"] = metrics.get("converted_leads", 0)
            
        elif skill_key == "time_management":
            evidence["metrics"]["response_time"] = metrics.get("average_response_time_hours")
            evidence["metrics"]["total_activities"] = metrics["total_activities"]
            evidence["metrics"]["activity_duration"] = metrics.get("total_activity_duration_hours")
            
        elif skill_key == "follow_up":
            evidence["metrics"]["total_activities"] = metrics["total_activities"]
            evidence["metrics"]["activity_types"] = metrics["activity_breakdown"]
        
        # Extract relevant strengths and improvements
        for strength in llm_analysis.get("strengths", []):
            if any(keyword in strength.lower() for keyword in self._get_skill_keywords(skill_key)):
                evidence["strengths"].append(strength)
        
        for improvement in llm_analysis.get("improvements", []):
            if any(keyword in improvement.lower() for keyword in self._get_skill_keywords(skill_key)):
                evidence["improvements"].append(improvement)
        
        return evidence
    
    def _get_skill_keywords(self, skill_key: str) -> List[str]:
        """Get keywords associated with each skill"""
        keywords = {
            "communication": ["communicate", "email", "call", "message", "respond", "engagement"],
            "relationship_building": ["rapport", "trust", "relationship", "connection", "personal"],
            "discovery": ["discover", "question", "understand", "need", "pain point", "requirement"],
            "presentation": ["present", "demo", "explain", "showcase", "solution"],
            "objection_handling": ["objection", "concern", "address", "handle", "overcome"],
            "closing": ["close", "convert", "deal", "win", "sign"],
            "time_management": ["time", "efficient", "quick", "response", "prioritize"],
            "follow_up": ["follow", "persist", "consistent", "touch point", "reminder"]
        }
        return keywords.get(skill_key, [])
    
    async def _rate_skill(
        self,
        session: Session,
        user: User,
        skill_info: Dict[str, str],
        evidence: Dict[str, Any],
        overall_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Rate a specific skill using LLM"""
        prompt = f"""
        You are an expert sales coach analyzing a sales representative's {skill_info['name']} skill. Provide a detailed assessment with specific improvement recommendations.

        SKILL ASSESSMENT: {skill_info['name']}
        Description: {skill_info['description']}
        
        PERFORMANCE EVIDENCE:
        Quantitative Metrics: {json.dumps(evidence['metrics'], indent=2)}
        Observed Strengths: {evidence['strengths']}
        Improvement Areas: {evidence['improvements']}
        
        CONTEXT:
        - Conversion Rate: {overall_metrics['conversion_rate']}%
        - Total Activities: {overall_metrics['total_activities']}
        - Activity Volume: {overall_metrics.get('total_leads', 0)} leads managed
        
        RATING SCALE:
        1 = Beginner (significant gaps, requires foundational development)
        2 = Developing (basic competency, needs structured improvement)
        3 = Competent (meets standards, room for optimization)
        4 = Advanced (exceeds standards, minor refinements needed)
        5 = Expert (exceptional performance, mentoring others)
        
        Provide detailed assessment in JSON format:
        {{
            "level": 3,
            "confidence": 85,
            "evidence": "2-3 sentences summarizing key evidence for this rating",
            "evidence_count": 5,
            "behavioral_observations": [
                "Specific behaviors observed that support this rating"
            ],
            "improvement_roadmap": {{
                "immediate_actions": [
                    "Actions they can take this week"
                ],
                "30_day_goals": [
                    "Goals to achieve in the next month"
                ],
                "skill_building_exercises": [
                    "Specific exercises to practice this skill"
                ]
            }},
            "success_indicators": [
                "Metrics to track improvement in this skill area"
            ],
            "benchmarks": {{
                "current_performance": "How they compare to standards",
                "target_performance": "What good performance looks like",
                "exceptional_performance": "What great performance looks like"
            }},
            "suggestions": "Primary improvement recommendation"
        }}
        """
        
        try:
            response = await llm_service.generate_response(user, session, [{"role": "user", "content": prompt}], temperature=0.3)
            
            # Parse JSON response - check if it's already a dict or needs parsing
            if isinstance(response, dict):
                rating_data = response.get('content', response)
                if isinstance(rating_data, str):
                    rating_data = json.loads(rating_data)
            else:
                rating_data = json.loads(response)
            
            return {
                "level": max(1, min(5, rating_data.get("level", 3))),
                "confidence": max(1, min(100, rating_data.get("confidence", 70))),
                "evidence": rating_data.get("evidence", "Based on available activity data."),
                "evidence_count": rating_data.get("evidence_count", len(evidence["metrics"])),
                "suggestions": rating_data.get("suggestions"),
                "behavioral_observations": rating_data.get("behavioral_observations", []),
                "improvement_roadmap": rating_data.get("improvement_roadmap", {}),
                "success_indicators": rating_data.get("success_indicators", []),
                "benchmarks": rating_data.get("benchmarks", {})
            }
            
        except Exception as e:
            logger.error(f"Skill rating failed: {str(e)}")
            # Fallback rating based on simple heuristics
            level = 3  # Default to competent
            if skill_info["id"] == "sales_closing" and overall_metrics["conversion_rate"] > 20:
                level = 4
            elif skill_info["id"] == "sales_communication" and evidence["metrics"].get("engagement_score", 0) > 7:
                level = 4
                
            return {
                "level": level,
                "confidence": 60,
                "evidence": f"Based on {overall_metrics['total_activities']} activities analyzed.",
                "evidence_count": overall_metrics["total_activities"],
                "suggestions": f"Continue developing {skill_info['name']} through practice and training.",
                "behavioral_observations": [f"Consistent activity patterns with {overall_metrics['total_activities']} tracked interactions"],
                "improvement_roadmap": {
                    "immediate_actions": [f"Focus on increasing {skill_info['name']} proficiency"],
                    "30_day_goals": [f"Improve {skill_info['name']} effectiveness through practice"],
                    "skill_building_exercises": [f"Practice {skill_info['name']} techniques regularly"]
                },
                "success_indicators": [f"Improved outcomes in {skill_info['name']}-related activities"],
                "benchmarks": {
                    "current_performance": "Meeting basic standards",
                    "target_performance": "Consistently strong performance",
                    "exceptional_performance": "Top-tier professional capability"
                }
            }
    
    async def _analyze_conversation_transcript(
        self,
        session: Session,
        user: User,
        transcript: str,
        conversation_type: str,
        lead_info: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze a conversation transcript and generate feedback"""
        prompt = f"""
        Analyze this {conversation_type} sales conversation and provide constructive feedback:
        
        Customer Information:
        {json.dumps(lead_info, indent=2) if lead_info else "Not available"}
        
        Transcript:
        {transcript[:10000]}  # Limit transcript length
        
        Please analyze and provide:
        1. Brief summary of the conversation (2-3 sentences)
        2. What the sales rep did well (with specific examples)
        3. Areas for improvement (with specific moments)
        4. Missed opportunities (what could have been said/done)
        5. Specific techniques or phrases to try next time
        
        For each feedback item, include:
        - Type: strength, improvement, technique, or missed_opportunity
        - Category: communication, discovery, objection_handling, closing, etc.
        - Specific moment or quote from the transcript (if applicable)
        - Suggested alternative response (for improvements)
        - Impact level: high, medium, or low
        - Confidence score: 1-100
        
        Format response as JSON with keys:
        - summary: Brief conversation summary
        - feedback_items: Array of feedback objects
        """
        
        try:
            response = await llm_service.generate_response(user, session, [{"role": "user", "content": prompt}], temperature=0.3)
            
            # Parse JSON response - check if it's already a dict or needs parsing
            if isinstance(response, dict):
                analysis = response.get('content', response)
                if isinstance(analysis, str):
                    analysis = json.loads(analysis)
            else:
                analysis = json.loads(response)
            
            # Validate and clean feedback items
            feedback_items = []
            for item in analysis.get("feedback_items", []):
                feedback_items.append({
                    "type": item.get("type", "improvement"),
                    "category": item.get("category", "communication"),
                    "text": item.get("text", ""),
                    "moment": item.get("moment"),
                    "suggestion": item.get("suggestion"),
                    "impact": item.get("impact", "medium"),
                    "confidence": max(1, min(100, item.get("confidence", 80)))
                })
            
            return {
                "summary": analysis.get("summary", "Conversation analyzed."),
                "feedback_items": feedback_items
            }
            
        except Exception as e:
            logger.error(f"Transcript analysis failed: {str(e)}")
            return {
                "summary": "Unable to generate detailed analysis.",
                "feedback_items": [{
                    "type": "improvement",
                    "category": "general",
                    "text": "Continue to focus on understanding customer needs.",
                    "impact": "medium",
                    "confidence": 50
                }]
            }


    async def analyze_team_performance(
        self,
        session: Session,
        current_user: User,
        period_months: int = 3
    ) -> Dict[str, Any]:
        """Analyze team performance for managers"""
        try:
            # Import here to avoid circular imports
            from app.models import DarwinBoxEmployee, EmployeeGitHubMapping, GitHubOAuth
            from sqlmodel import select
            
            # Find if current user is a manager in DarwinBox
            darwinbox_employee = None
            
            # Check if user has GitHub OAuth
            github_oauth = session.exec(
                select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
            ).first()
            
            if github_oauth:
                # Check if there's a mapping via GitHub username
                mapping = session.exec(
                    select(EmployeeGitHubMapping).where(
                        EmployeeGitHubMapping.github_username == github_oauth.github_username
                    )
                ).first()
                
                if mapping:
                    darwinbox_employee = mapping.darwinbox_employee
            
            # If not found via GitHub, check by email
            if not darwinbox_employee:
                darwinbox_employee = session.exec(
                    select(DarwinBoxEmployee).where(
                        DarwinBoxEmployee.email == current_user.email
                    )
                ).first()
            
            if not darwinbox_employee or not darwinbox_employee.is_manager:
                raise HTTPException(
                    status_code=403,
                    detail="You must be a manager to access team performance data"
                )
            
            # Get team members - fixed to use reporting_manager_id instead of manager_id
            team_members = session.exec(
                select(DarwinBoxEmployee).where(
                    DarwinBoxEmployee.reporting_manager_id == darwinbox_employee.darwinbox_id,
                    DarwinBoxEmployee.employment_status == "active"
                )
            ).all()
            
            if not team_members:
                return {
                    "team_stats": {
                        "total_members": 0,
                        "members_with_crm": 0,
                        "avg_overall_score": 0,
                        "avg_conversion_rate": 0,
                        "total_activities": 0,
                        "total_leads": 0
                    },
                    "member_performance": [],
                    "skill_aggregates": {},
                    "team_insights": {
                        "strengths": ["No team data available"],
                        "improvements": ["Add team members to see performance data"]
                    }
                }
            
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=period_months * 30)
            
            # Analyze each team member's performance
            member_performances = []
            all_skill_ratings = []
            total_activities = 0
            total_leads = 0
            conversion_rates = []
            
            for member in team_members:
                # Find CRM auth for this team member
                member_user = session.exec(
                    select(User).where(User.email == member.email)
                ).first()
                
                if not member_user:
                    continue
                
                crm_auth = session.exec(
                    select(ScalerCRMAuth).where(
                        ScalerCRMAuth.owner_id == member_user.id,
                        ScalerCRMAuth.is_active == True
                    )
                ).first()
                
                if not crm_auth:
                    # Member doesn't have CRM connected
                    member_performances.append({
                        "member_id": str(member.id),
                        "member_email": member.email,
                        "member_name": member.full_name,
                        "has_crm_connected": False,
                        "performance": None
                    })
                    continue
                
                # Get performance metrics for this member
                metrics = await self._calculate_performance_metrics(
                    session, crm_auth, start_date, end_date
                )
                
                # Get latest performance analysis
                latest_analysis = session.exec(
                    select(SalesPerformanceAnalysis).where(
                        SalesPerformanceAnalysis.crm_auth_id == crm_auth.id
                    ).order_by(SalesPerformanceAnalysis.created_at.desc())
                ).first()
                
                # Get skill ratings
                skill_ratings = []
                if latest_analysis:
                    skill_ratings = session.exec(
                        select(SalesSkillRating).where(
                            SalesSkillRating.analysis_id == latest_analysis.id
                        )
                    ).all()
                    all_skill_ratings.extend(skill_ratings)
                
                # Calculate overall score (simple average of skill levels)
                overall_score = 0
                if skill_ratings:
                    overall_score = sum(r.inferred_level for r in skill_ratings) / len(skill_ratings) * 20  # Convert 1-5 to 0-100
                
                total_activities += metrics["total_activities"]
                total_leads += metrics["total_leads"]
                if metrics["conversion_rate"] > 0:
                    conversion_rates.append(metrics["conversion_rate"])
                
                member_performances.append({
                    "member_id": str(member.id),
                    "member_email": member.email,
                    "member_name": member.full_name,
                    "has_crm_connected": True,
                    "performance": {
                        "overall_score": round(overall_score, 1),
                        "conversion_rate": metrics["conversion_rate"],
                        "total_activities": metrics["total_activities"],
                        "total_leads": metrics["total_leads"],
                        "avg_response_time": metrics.get("average_response_time_hours"),
                        "activity_breakdown": metrics["activity_breakdown"],
                        "skill_ratings": [
                            {
                                "skill_id": r.skill_id,
                                "skill_name": r.skill_name,
                                "inferred_level": r.inferred_level,
                                "confidence_score": r.confidence_score
                            }
                            for r in skill_ratings
                        ]
                    }
                })
            
            # Calculate team statistics
            members_with_crm = len([m for m in member_performances if m["has_crm_connected"]])
            avg_conversion_rate = sum(conversion_rates) / len(conversion_rates) if conversion_rates else 0
            
            # Calculate overall scores for members with performance data
            member_scores = [m["performance"]["overall_score"] for m in member_performances if m["performance"]]
            avg_overall_score = sum(member_scores) / len(member_scores) if member_scores else 0
            
            # Aggregate skills across team
            skill_aggregates = {}
            for rating in all_skill_ratings:
                if rating.skill_id not in skill_aggregates:
                    skill_aggregates[rating.skill_id] = {
                        "skill_name": rating.skill_name,
                        "total_ratings": 0,
                        "sum_levels": 0,
                        "avg_level": 0,
                        "coverage": 0
                    }
                skill_aggregates[rating.skill_id]["total_ratings"] += 1
                skill_aggregates[rating.skill_id]["sum_levels"] += rating.inferred_level
            
            # Calculate averages and coverage
            for skill_id, data in skill_aggregates.items():
                data["avg_level"] = round(data["sum_levels"] / data["total_ratings"], 1)
                data["coverage"] = round((data["total_ratings"] / members_with_crm * 100), 0) if members_with_crm > 0 else 0
            
            # Generate team insights
            team_insights = await self._generate_team_insights(
                session, current_user, member_performances, skill_aggregates
            )
            
            return {
                "team_stats": {
                    "total_members": len(team_members),
                    "members_with_crm": members_with_crm,
                    "avg_overall_score": round(avg_overall_score, 1),
                    "avg_conversion_rate": round(avg_conversion_rate, 2),
                    "total_activities": total_activities,
                    "total_leads": total_leads
                },
                "member_performance": member_performances,
                "skill_aggregates": skill_aggregates,
                "team_insights": team_insights
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Team performance analysis failed: {str(e)}")
            raise
    
    async def _generate_team_insights(
        self,
        session: Session,
        user: User,
        member_performances: List[Dict[str, Any]],
        skill_aggregates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate insights about team performance"""
        # Identify top skills and gaps
        if skill_aggregates:
            top_skills = sorted(
                [(data["skill_name"], data["avg_level"]) for data in skill_aggregates.values()],
                key=lambda x: x[1],
                reverse=True
            )[:3]
            
            skill_gaps = sorted(
                [(data["skill_name"], data["avg_level"]) for data in skill_aggregates.values()],
                key=lambda x: x[1]
            )[:3]
        else:
            top_skills = []
            skill_gaps = []
        
        # Performance distribution
        performers_with_data = [m for m in member_performances if m["performance"]]
        high_performers = len([m for m in performers_with_data if m["performance"]["overall_score"] >= 70])
        low_performers = len([m for m in performers_with_data if m["performance"]["overall_score"] < 50])
        
        strengths = []
        improvements = []
        
        # Team strengths
        if top_skills:
            strengths.append(f"Strong team capabilities in {', '.join([s[0] for s in top_skills[:2]])}")
        
        if high_performers > len(performers_with_data) * 0.3:
            strengths.append(f"{high_performers} team members performing above expectations")
        
        # Areas for improvement
        if skill_gaps and skill_gaps[0][1] < 3:
            improvements.append(f"Team-wide training needed for {skill_gaps[0][0]}")
        
        if low_performers > len(performers_with_data) * 0.2:
            improvements.append(f"{low_performers} team members need coaching support")
        
        members_without_crm = len([m for m in member_performances if not m["has_crm_connected"]])
        if members_without_crm > 0:
            improvements.append(f"{members_without_crm} team members need to connect their CRM")
        
        return {
            "strengths": strengths or ["Team is performing at expected levels"],
            "improvements": improvements or ["Continue current development initiatives"],
            "top_skills": [f"{skill} (avg: {level:.1f}/5)" for skill, level in top_skills],
            "skill_gaps": [f"{skill} (avg: {level:.1f}/5)" for skill, level in skill_gaps],
            "performance_distribution": {
                "high_performers": high_performers,
                "average_performers": len(performers_with_data) - high_performers - low_performers,
                "low_performers": low_performers,
                "no_data": len(member_performances) - len(performers_with_data)
            }
        }


# Create singleton instance
sales_analysis_service = SalesAnalysisService()
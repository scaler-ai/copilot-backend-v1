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
from sqlmodel import Session, select, func
from app.models import (
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
                metrics, activity_summary
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
                strengths_identified=llm_analysis["strengths"],
                improvement_areas=llm_analysis["improvements"],
                crm_auth_id=crm_auth.id
            )
            session.add(analysis)
            session.commit()
            
            # Generate skill ratings
            skill_ratings = await self._generate_skill_ratings(
                session, analysis, metrics, activity_summary, llm_analysis
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
            
            # Analyze conversation with LLM
            analysis = await self._analyze_conversation_transcript(
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
                prev_date = datetime.fromisoformat(activities[i-1].activity_date)
                curr_date = datetime.fromisoformat(activity.activity_date)
                hours_diff = (curr_date - prev_date).total_seconds() / 3600
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
            "average_response_time_hours": round(avg_response_time, 2) if avg_response_time else None,
            "average_engagement_score": round(avg_engagement, 2) if avg_engagement else None,
            "total_activity_duration_hours": round(total_duration / 60, 2),
            "activity_breakdown": activity_breakdown,
            "lead_stage_distribution": stage_distribution,
            "conversations_with_transcripts": len([c for c in conversations if c.transcript_available])
        }
    
    def _prepare_activity_summary(self, activities: List[ScalerActivity]) -> Dict[str, Any]:
        """Prepare activity data for LLM analysis"""
        summary = {
            "total_activities": len(activities),
            "activity_types": {},
            "outcomes": {},
            "high_engagement_activities": [],
            "patterns": []
        }
        
        # Analyze activities
        for activity in activities:
            # Count types
            summary["activity_types"][activity.activity_type] = (
                summary["activity_types"].get(activity.activity_type, 0) + 1
            )
            
            # Count outcomes
            if activity.outcome:
                summary["outcomes"][activity.outcome] = (
                    summary["outcomes"].get(activity.outcome, 0) + 1
                )
            
            # Track high engagement
            if activity.engagement_score and activity.engagement_score >= 8:
                summary["high_engagement_activities"].append({
                    "type": activity.activity_type,
                    "subject": activity.activity_subject,
                    "outcome": activity.outcome,
                    "score": activity.engagement_score
                })
        
        # Identify patterns
        if summary["activity_types"]:
            most_common = max(summary["activity_types"], key=summary["activity_types"].get)
            summary["patterns"].append(f"Most common activity type: {most_common}")
        
        return summary
    
    async def _generate_performance_analysis(
        self,
        metrics: Dict[str, Any],
        activity_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate performance analysis using LLM"""
        prompt = f"""
        Analyze the following sales performance data and provide insights:
        
        Performance Metrics:
        - Total leads: {metrics['total_leads']}
        - Conversion rate: {metrics['conversion_rate']}%
        - Total activities: {metrics['total_activities']}
        - Average response time: {metrics.get('average_response_time_hours', 'N/A')} hours
        - Average engagement score: {metrics.get('average_engagement_score', 'N/A')}/10
        
        Activity Breakdown:
        {json.dumps(metrics['activity_breakdown'], indent=2)}
        
        Lead Stage Distribution:
        {json.dumps(metrics['lead_stage_distribution'], indent=2)}
        
        Activity Patterns:
        {json.dumps(activity_summary, indent=2)}
        
        Based on this data, provide:
        1. A summary of the sales rep's performance (2-3 sentences)
        2. List 3-5 key strengths demonstrated
        3. List 3-5 areas for improvement
        4. Overall performance rating (1-10)
        
        Format as JSON with keys: summary, strengths (array), improvements (array), rating
        """
        
        try:
            response = await llm_service.generate(prompt, temperature=0.3)
            
            # Parse JSON response
            analysis = json.loads(response)
            
            # Ensure required fields
            return {
                "summary": analysis.get("summary", "Performance analysis completed."),
                "strengths": analysis.get("strengths", []),
                "improvements": analysis.get("improvements", []),
                "rating": analysis.get("rating", 5)
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
                skill_info, skill_evidence, metrics
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
        skill_info: Dict[str, str],
        evidence: Dict[str, Any],
        overall_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Rate a specific skill using LLM"""
        prompt = f"""
        Rate the sales representative's {skill_info['name']} skill based on the following evidence:
        
        Skill: {skill_info['name']}
        Description: {skill_info['description']}
        
        Evidence:
        - Metrics: {json.dumps(evidence['metrics'], indent=2)}
        - Identified Strengths: {evidence['strengths']}
        - Areas for Improvement: {evidence['improvements']}
        
        Overall Performance Context:
        - Conversion Rate: {overall_metrics['conversion_rate']}%
        - Total Activities: {overall_metrics['total_activities']}
        
        Provide a rating from 1-5 where:
        1 = Beginner
        2 = Developing
        3 = Competent
        4 = Advanced
        5 = Expert
        
        Also provide:
        - Confidence score (1-100) in your rating
        - Brief evidence summary (2-3 sentences)
        - Number of data points supporting this rating
        - Specific improvement suggestion
        
        Format as JSON with keys: level, confidence, evidence, evidence_count, suggestions
        """
        
        try:
            response = await llm_service.generate(prompt, temperature=0.3)
            rating_data = json.loads(response)
            
            return {
                "level": max(1, min(5, rating_data.get("level", 3))),
                "confidence": max(1, min(100, rating_data.get("confidence", 70))),
                "evidence": rating_data.get("evidence", "Based on available activity data."),
                "evidence_count": rating_data.get("evidence_count", len(evidence["metrics"])),
                "suggestions": rating_data.get("suggestions")
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
                "suggestions": f"Continue developing {skill_info['name']} through practice and training."
            }
    
    async def _analyze_conversation_transcript(
        self,
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
            response = await llm_service.generate(prompt, temperature=0.3)
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


# Create singleton instance
sales_analysis_service = SalesAnalysisService()
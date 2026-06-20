from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class SearchImage:
    position: int
    url_base: Optional[str]
    caption: Optional[str]


@dataclass
class SearchListing:
    id: str
    url: str
    display_address: Optional[str]
    price: Optional[int]            
    price_currency: str
    property_sub_type: Optional[str]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]
    agent_branch_id: Optional[int]
    agent_branch_display_name: Optional[str]
    agent_branch_name: Optional[str]
    agent_phone: Optional[str]
    agent_logo_uri: Optional[str]
    tenure_type: Optional[str]
    summary: Optional[str]           
    key_features: List[str] = field(default_factory=list)
    images: List[SearchImage] = field(default_factory=list)
    added_or_reduced: Optional[str] = None
    listing_update_reason: Optional[str] = None
    listing_update_date: Optional[str] = None


@dataclass
class DetailImage:
    position: int
    url_base: Optional[str]
    url_large: Optional[str]      
    url_medium: Optional[str]    
    url_thumbnail: Optional[str]  
    caption: Optional[str]


@dataclass
class DetailListing:
    listing_id: Optional[str]
    enc_id: Optional[str]
    price: Optional[int]           
    price_raw: Optional[str]       
    price_qualifier: str           
    outcode: Optional[str]         
    incode: Optional[str]          
    full_postcode: Optional[str]   
    country_code: Optional[str]
    uk_country: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    description_html: Optional[str]
    description_text: Optional[str]
    images: List[DetailImage] = field(default_factory=list)
    agent_branch_id: Optional[int] = None
    agent_branch_name: Optional[str] = None
    agent_branch_display_name: Optional[str] = None
    agent_company_name: Optional[str] = None
    agent_company_trading_name: Optional[str] = None
    agent_display_address: Optional[str] = None
    agent_profile_url: Optional[str] = None
    agent_logo_path: Optional[str] = None
    is_published: Optional[bool] = None
    is_archived: Optional[bool] = None
    property_sub_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
